"""Persistent SQLite state for operations."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

OUTPUT_CAP_BYTES = 1 * 1024 * 1024
RETENTION_DAYS = 90
TRUNCATION_MARKER = "\n...[truncated]"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)


def _redact(text: str) -> str:
    return _BEARER_RE.sub("Bearer [redacted]", text)


def truncate_output(
    text: Optional[str], cap: int = OUTPUT_CAP_BYTES, truncated: bool = False
) -> tuple[Optional[str], bool]:
    if text is None:
        return None, False
    text = _redact(text)
    if not truncated and len(text) <= cap:
        return text, False
    marker = TRUNCATION_MARKER
    if cap <= len(marker):
        return text[:cap], True
    body = text[: cap - len(marker)]
    return body + marker, True


class PackageUpdate(BaseModel):
    name: str
    current: Optional[str] = None
    candidate: Optional[str] = None


class UpdateCheckResult(BaseModel):
    packages: list[PackageUpdate] = Field(default_factory=list)
    count: int = 0


class UpdateApplyResult(BaseModel):
    reboot_required: bool = False
    output: Optional[str] = None


class Job(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_type: str
    status: str = "queued"
    credential_identity: str
    correlation_id: str
    created_at: datetime = Field(default_factory=utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    output: Optional[str] = None
    output_truncated: bool = False
    result: Optional[dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class PowerAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action_type: str
    delay_seconds: int
    status: str = "pending"
    credential_identity: str
    correlation_id: str
    created_at: datetime = Field(default_factory=utcnow)
    scheduled_for: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    output: Optional[str] = None
    output_truncated: bool = False
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class AuditRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=utcnow)
    credential_identity: str
    correlation_id: str
    operation: str
    outcome: str
    status: Optional[str] = None
    error_code: Optional[str] = None
    message: Optional[str] = None
    details: Optional[str] = None


def _dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _json_dumps(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, default=str)


def _json_loads(value: Optional[str]) -> Optional[Any]:
    if value is None:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


class StateStore:
    """SQLite-backed persistent state."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.db_path), timeout=30, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()
        self.cleanup()
        self.reconcile_interrupted_jobs()
        self.reconcile_power_actions()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    credential_identity TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    output TEXT,
                    output_truncated INTEGER NOT NULL DEFAULT 0,
                    result_json TEXT,
                    error_code TEXT,
                    error_message TEXT
                );
                CREATE TABLE IF NOT EXISTS power_actions (
                    id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    delay_seconds INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    credential_identity TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    scheduled_for TEXT,
                    finished_at TEXT,
                    output TEXT,
                    output_truncated INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    error_message TEXT
                );
                CREATE TABLE IF NOT EXISTS audit_records (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    credential_identity TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    status TEXT,
                    error_code TEXT,
                    message TEXT,
                    details TEXT
                );
                """
            )
            self._conn.commit()

    def cleanup(self, retention_days: int = RETENTION_DAYS) -> None:
        cutoff = (utcnow() - timedelta(days=retention_days)).isoformat()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM jobs WHERE created_at < ?", (cutoff,))
            cur.execute("DELETE FROM power_actions WHERE created_at < ?", (cutoff,))
            cur.execute("DELETE FROM audit_records WHERE timestamp < ?", (cutoff,))
            self._conn.commit()

    # ---- jobs ----
    def create_job(self, job: Job) -> Job:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO jobs (id, job_type, status, credential_identity, correlation_id,
                    created_at, started_at, finished_at, output, output_truncated, result_json,
                    error_code, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.job_type,
                    job.status,
                    job.credential_identity,
                    job.correlation_id,
                    job.created_at.isoformat(),
                    job.started_at.isoformat() if job.started_at else None,
                    job.finished_at.isoformat() if job.finished_at else None,
                    job.output,
                    1 if job.output_truncated else 0,
                    _json_dumps(job.result),
                    job.error_code,
                    job.error_message,
                ),
            )
            self._conn.commit()
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_job(row)

    def list_jobs(self, limit: int = 100) -> list[Job]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def update_job(self, job_id: str, **fields: Any) -> Optional[Job]:
        allowed = {
            "status",
            "started_at",
            "finished_at",
            "output",
            "output_truncated",
            "result",
            "error_code",
            "error_message",
        }
        sets = []
        params: list[Any] = []
        for key, value in fields.items():
            if key == "result":
                sets.append("result_json = ?")
                params.append(_json_dumps(value))
            elif key in allowed:
                col = key
                if key in {"started_at", "finished_at"} and isinstance(value, datetime):
                    value = value.isoformat()
                if key == "output_truncated":
                    value = 1 if value else 0
                sets.append(f"{col} = ?")
                params.append(value)
            else:
                continue
        if not sets:
            return self.get_job(job_id)
        params.append(job_id)
        with self._lock:
            self._conn.execute(
                f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", params
            )
            self._conn.commit()
        return self.get_job(job_id)

    def reconcile_interrupted_jobs(self) -> list[str]:
        now = utcnow().isoformat()
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM jobs WHERE status IN ('queued', 'running')"
            ).fetchall()
            ids = [r["id"] for r in rows]
            self._conn.execute(
                """
                UPDATE jobs SET status = 'failed', error_code = 'interrupted',
                    error_message = 'operation interrupted by service restart',
                    finished_at = ? WHERE status IN ('queued', 'running')
                """,
                (now,),
            )
            self._conn.commit()
        return ids

    def has_active_jobs(self) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM jobs WHERE status IN ('queued', 'running')"
            ).fetchone()
        return bool(row and row["c"] > 0)

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            job_type=row["job_type"],
            status=row["status"],
            credential_identity=row["credential_identity"],
            correlation_id=row["correlation_id"],
            created_at=_dt(row["created_at"]) or utcnow(),
            started_at=_dt(row["started_at"]),
            finished_at=_dt(row["finished_at"]),
            output=row["output"],
            output_truncated=bool(row["output_truncated"]),
            result=_json_loads(row["result_json"]),
            error_code=row["error_code"],
            error_message=row["error_message"],
        )

    # ---- power actions ----
    def create_power_action(self, action: PowerAction) -> PowerAction:
        if action.scheduled_for is None:
            action.scheduled_for = action.created_at + timedelta(seconds=action.delay_seconds)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO power_actions (id, action_type, delay_seconds, status,
                    credential_identity, correlation_id, created_at, scheduled_for,
                    finished_at, output, output_truncated, error_code, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action.id,
                    action.action_type,
                    action.delay_seconds,
                    action.status,
                    action.credential_identity,
                    action.correlation_id,
                    action.created_at.isoformat(),
                    action.scheduled_for.isoformat() if action.scheduled_for else None,
                    action.finished_at.isoformat() if action.finished_at else None,
                    action.output,
                    1 if action.output_truncated else 0,
                    action.error_code,
                    action.error_message,
                ),
            )
            self._conn.commit()
        return action

    def get_power_action(self, action_id: str) -> Optional[PowerAction]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM power_actions WHERE id = ?", (action_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_power(row)

    def list_power_actions(self, limit: int = 100) -> list[PowerAction]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM power_actions ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_power(r) for r in rows]

    def update_power_action(self, action_id: str, **fields: Any) -> Optional[PowerAction]:
        allowed = {
            "status",
            "scheduled_for",
            "finished_at",
            "output",
            "output_truncated",
            "error_code",
            "error_message",
        }
        sets = []
        params: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key in {"scheduled_for", "finished_at"} and isinstance(value, datetime):
                value = value.isoformat()
            if key == "output_truncated":
                value = 1 if value else 0
            sets.append(f"{key} = ?")
            params.append(value)
        if not sets:
            return self.get_power_action(action_id)
        params.append(action_id)
        with self._lock:
            self._conn.execute(
                f"UPDATE power_actions SET {', '.join(sets)} WHERE id = ?", params
            )
            self._conn.commit()
        return self.get_power_action(action_id)

    def has_pending_power(self) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM power_actions WHERE status = 'pending'"
            ).fetchone()
        return bool(row and row["c"] > 0)

    def get_pending_power(self) -> Optional[PowerAction]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM power_actions WHERE status = 'pending' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return self._row_to_power(row)

    def reconcile_power_actions(self) -> list[str]:
        now = utcnow()
        unknown: list[str] = []
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM power_actions WHERE status = 'pending'"
            ).fetchall()
            for row in rows:
                scheduled_for = _dt(row["scheduled_for"])
                if scheduled_for is not None and scheduled_for <= now:
                    unknown.append(row["id"])
            if unknown:
                placeholders = ",".join("?" for _ in unknown)
                self._conn.execute(
                    f"""
                    UPDATE power_actions SET status = 'unknown', error_code = 'unconfirmed_execution',
                        error_message = 'scheduled time passed while service was unavailable; execution unconfirmed',
                        finished_at = ? WHERE id IN ({placeholders})
                    """,
                    (now.isoformat(), *unknown),
                )
                self._conn.commit()
        return unknown

    def _row_to_power(self, row: sqlite3.Row) -> PowerAction:
        return PowerAction(
            id=row["id"],
            action_type=row["action_type"],
            delay_seconds=row["delay_seconds"],
            status=row["status"],
            credential_identity=row["credential_identity"],
            correlation_id=row["correlation_id"],
            created_at=_dt(row["created_at"]) or utcnow(),
            scheduled_for=_dt(row["scheduled_for"]),
            finished_at=_dt(row["finished_at"]),
            output=row["output"],
            output_truncated=bool(row["output_truncated"]),
            error_code=row["error_code"],
            error_message=row["error_message"],
        )

    # ---- audit ----
    def create_audit(self, record: AuditRecord) -> AuditRecord:
        details = record.details
        details, _ = truncate_output(details)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO audit_records (id, timestamp, credential_identity, correlation_id,
                    operation, outcome, status, error_code, message, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.timestamp.isoformat(),
                    record.credential_identity,
                    record.correlation_id,
                    record.operation,
                    record.outcome,
                    record.status,
                    record.error_code,
                    record.message,
                    details,
                ),
            )
            self._conn.commit()
        record.details = details
        return record

    def list_audit(self, limit: int = 100) -> list[AuditRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM audit_records ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        out = []
        for row in rows:
            out.append(
                AuditRecord(
                    id=row["id"],
                    timestamp=_dt(row["timestamp"]) or utcnow(),
                    credential_identity=row["credential_identity"],
                    correlation_id=row["correlation_id"],
                    operation=row["operation"],
                    outcome=row["outcome"],
                    status=row["status"],
                    error_code=row["error_code"],
                    message=row["message"],
                    details=row["details"],
                )
            )
        return out

