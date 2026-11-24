import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from linux_monitor.operations import (
    AuditRecord,
    Job,
    PowerAction,
    StateStore,
    truncate_output,
    utcnow,
)
from linux_monitor.operations.errors import OperationError


def test_truncate_output_caps_and_marks(tmp_path):
    text = "a" * (1024 * 1024 + 10)
    out, truncated = truncate_output(text)
    assert truncated is True
    assert len(out) <= 1024 * 1024
    assert out.endswith("...[truncated]")


def test_store_persists_job_and_power_and_audit(tmp_path):
    db = tmp_path / "state.db"
    store = StateStore(db)
    job = Job(job_type="update_check", credential_identity="reader", correlation_id="c1", status="queued")
    store.create_job(job)
    job2 = store.get_job(job.id)
    assert job2 is not None
    assert job2.status == "queued"
    assert job2.credential_identity == "reader"

    action = PowerAction(action_type="reboot", delay_seconds=60, credential_identity="admin", correlation_id="c2")
    store.create_power_action(action)
    assert store.get_power_action(action.id).status == "pending"
    assert store.has_pending_power()

    store.create_audit(AuditRecord(credential_identity="admin", correlation_id="c3", operation="test", outcome="success"))
    assert store.list_audit()[0].operation == "test"
    store.close()


def test_store_reconciles_interrupted_jobs(tmp_path):
    db = tmp_path / "state.db"
    store = StateStore(db)
    job = Job(job_type="update_check", credential_identity="reader", correlation_id="c1", status="running")
    store.create_job(job)
    store.close()

    store2 = StateStore(db)
    updated = store2.get_job(job.id)
    assert updated.status == "failed"
    assert updated.error_code == "interrupted"
    store2.close()


def test_store_cleanup_retention(tmp_path):
    db = tmp_path / "state.db"
    store = StateStore(db)
    old = Job(job_type="update_check", credential_identity="reader", correlation_id="c1", status="succeeded")
    old.created_at = utcnow() - timedelta(days=91)
    store.create_job(old)
    # force cleanup
    store.cleanup(retention_days=90)
    assert store.get_job(old.id) is None
    store.close()


def test_store_power_reconcile_missed(tmp_path):
    db = tmp_path / "state.db"
    store = StateStore(db)
    action = PowerAction(action_type="reboot", delay_seconds=60, credential_identity="admin", correlation_id="c2")
    action.created_at = utcnow() - timedelta(seconds=200)
    action.scheduled_for = action.created_at + timedelta(seconds=60)
    store.create_power_action(action)
    store.close()
    store2 = StateStore(db)
    # reconcile called in constructor already
    updated = store2.get_power_action(action.id)
    assert updated.status == "unknown"
    store2.close()