"""Typed asynchronous APT job manager."""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager, nullcontext
from typing import Any, Callable, Optional

from .errors import ConflictError, ExecutionError, InvalidInputError, TimeoutOperationError
from .process_runner import ProcessResult
from .store import Job, StateStore, truncate_output, utcnow

CHECK_TIMEOUT_SECONDS = 15 * 60
APPLY_TIMEOUT_SECONDS = 2 * 60 * 60


def _null_async_context():
    return nullcontext()


class JobManager:
    def __init__(
        self,
        store: StateStore,
        process_runner: Any,
        helper_path: str,
        *,
        sudo_path: str = "/usr/bin/sudo",
        use_sudo: bool = True,
        power_service: Optional[Any] = None,
        operation_lock: Optional[asyncio.Lock] = None,
    ) -> None:
        self.store = store
        self.process_runner = process_runner
        self.helper_path = helper_path
        self.sudo_path = sudo_path
        self.use_sudo = use_sudo
        self.power_service = power_service
        self.operation_lock = operation_lock
        self._active_job_id: Optional[str] = None
        self._tasks: dict[str, asyncio.Task] = {}
        store.reconcile_interrupted_jobs()

    def set_power_service(self, power_service: Any) -> None:
        self.power_service = power_service

    def _lock_context(self):
        if self.operation_lock is None:
            return nullcontext()
        return self.operation_lock

    def has_active_apt(self) -> bool:
        return self._active_job_id is not None or self.store.has_active_jobs()

    def get_job(self, job_id: str) -> Optional[Job]:
        return self.store.get_job(job_id)

    def list_jobs(self, limit: int = 100) -> list[Job]:
        return self.store.list_jobs(limit=limit)

    def _helper_argv(self, operation: str) -> list[str]:
        if self.use_sudo and self.sudo_path:
            return [self.sudo_path, "-n", self.helper_path, operation]
        return [self.helper_path, operation]

    async def start_job(
        self,
        job_type: str,
        credential_identity: Optional[str] = None,
        correlation_id: Optional[str] = None,
        *,
        confirmed: bool = True,
        **kwargs: Any,
    ) -> Job:
        credential_identity = credential_identity or kwargs.get("credential_identity")
        correlation_id = correlation_id or kwargs.get("correlation_id")
        if job_type not in {"update_check", "update_apply"}:
            raise InvalidInputError("invalid_job_type", "job type must be update_check or update_apply")
        if credential_identity != "admin":
            raise InvalidInputError("invalid_credential", "credential identity must be admin")
        async with self._lock_context():
            if self.power_service is not None and getattr(self.power_service, "has_pending_power", lambda: False)():
                raise ConflictError("power_action_pending", "a power action is pending")
            if self._active_job_id is not None or self.store.has_active_jobs():
                raise ConflictError("operation_in_progress", "another APT operation is active")
            job = Job(
                job_type=job_type,
                credential_identity=credential_identity,
                correlation_id=correlation_id or str(uuid.uuid4()),
                status="queued",
            )
            self.store.create_job(job)
            self._active_job_id = job.id
        task = asyncio.create_task(self._execute(job.id))
        self._tasks[job.id] = task
        return job

    async def _execute(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        if job is None:
            self._active_job_id = None
            return
        is_check = job.job_type == "update_check"
        timeout = CHECK_TIMEOUT_SECONDS if is_check else APPLY_TIMEOUT_SECONDS
        operation = "apt-check" if is_check else "apt-apply"
        self.store.update_job(job_id, status="running", started_at=utcnow())
        try:
            argv = self._helper_argv(operation)
            result = await self.process_runner.run(argv, timeout=timeout, env=None)
            timed_out = bool(getattr(result, "timed_out", False))
            if timed_out:
                raise TimeoutOperationError("timeout", f"operation timed out after {timeout} seconds")
            returncode = getattr(result, "returncode", 1)
            stdout = getattr(result, "stdout", "") or ""
            stderr = getattr(result, "stderr", "") or ""
            stdout_truncated = bool(getattr(result, "stdout_truncated", False))
            if returncode != 0:
                message = (stderr.strip() or stdout.strip() or "helper failed")
                message, _ = truncate_output(message, truncated=bool(getattr(result, "stderr_truncated", False)))
                raise ExecutionError("helper_failed", message)
            try:
                data = json.loads(stdout or "{}")
            except json.JSONDecodeError as exc:
                raise ExecutionError("malformed_helper_output", f"invalid helper output: {exc}")
            if is_check:
                packages = []
                for item in (data.get("packages") or []):
                    if not isinstance(item, dict) or "name" not in item:
                        continue
                    packages.append(
                        {
                            "name": str(item.get("name")),
                            "current": item.get("current"),
                            "candidate": item.get("candidate"),
                        }
                    )
                result_payload = {"packages": packages, "count": len(packages)}
                output = None
                output_truncated = False
            else:
                result_payload = {
                    "reboot_required": bool(data.get("reboot_required", False)),
                }
                output, output_truncated = truncate_output(
                    data.get("output"),
                    truncated=bool(data.get("output_truncated", False)) or stdout_truncated,
                )
            self.store.update_job(
                job_id,
                status="succeeded",
                finished_at=utcnow(),
                output=output,
                output_truncated=output_truncated,
                result=result_payload,
            )
            self._record_audit(job, "success", None, None)
        except TimeoutOperationError as exc:
            output, output_truncated = truncate_output(getattr(exc, "details", None) or "")
            self.store.update_job(
                job_id,
                status="failed",
                finished_at=utcnow(),
                error_code=exc.code,
                error_message=exc.message,
                output=output or None,
                output_truncated=output_truncated,
            )
            self._record_audit(job, "failure", exc.code, exc.message)
        except ExecutionError as exc:
            output, output_truncated = truncate_output(getattr(exc, "details", None) or "")
            self.store.update_job(
                job_id,
                status="failed",
                finished_at=utcnow(),
                error_code=exc.code,
                error_message=exc.message,
                output=output or None,
                output_truncated=output_truncated,
            )
            self._record_audit(job, "failure", exc.code, exc.message)
        except (asyncio.TimeoutError, TimeoutError):
            self.store.update_job(
                job_id,
                status="failed",
                finished_at=utcnow(),
                error_code="timeout",
                error_message=f"operation timed out after {timeout} seconds",
            )
            self._record_audit(job, "failure", "timeout", f"operation timed out after {timeout} seconds")
        except Exception:
            message = "internal error"
            self.store.update_job(
                job_id,
                status="failed",
                finished_at=utcnow(),
                error_code="internal_error",
                error_message=message,
            )
            self._record_audit(job, "failure", "internal_error", message)
        finally:
            self._active_job_id = None
            self._tasks.pop(job_id, None)

    def _record_audit(self, job: Job, outcome: str, error_code: Optional[str], message: Optional[str]) -> None:
        try:
            from .store import AuditRecord

            self.store.create_audit(
                AuditRecord(
                    credential_identity=job.credential_identity,
                    correlation_id=job.correlation_id,
                    operation=job.job_type,
                    outcome=outcome,
                    status="succeeded" if outcome == "success" else "failed",
                    error_code=error_code,
                    message=message,
                )
            )
        except Exception:
            pass

    @asynccontextmanager
    async def _maybe_lock(self):
        if self.operation_lock is None:
            yield
            return
        async with self.operation_lock:
            yield

