import asyncio
import json
import os

import pytest
from fastapi.testclient import TestClient

from linux_monitor.config import Settings
from linux_monitor.main import create_app
from linux_monitor.operations import ProcessResult, StateStore


class FakeRunner:
    def __init__(self, result=None, exc=None, results=None, delay=0.0):
        self.result = result
        self.exc = exc
        self.results = list(results) if results else None
        self.delay = delay
        self.calls = []

    async def run(self, argv, *, timeout, env=None, cwd=None):
        self.calls.append((list(argv), timeout, env))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc is not None:
            raise self.exc
        if self.results is not None:
            if self.results:
                return self.results.pop(0)
            return ProcessResult(0, stdout="{}")
        return self.result


READER = "r" * 40
ADMIN = "a" * 40


def make_settings(tmp_path, **overrides):
    data = dict(
        reader_token=READER,
        admin_token=ADMIN,
        environment="test",
        database_path=str(tmp_path / "ops.db"),
        privileged_helper_path="/helper",
        sudo_path="/usr/bin/sudo",
    )
    data.update(overrides)
    return Settings(**data)


def make_client(tmp_path, runner, **settings_overrides):
    settings = make_settings(tmp_path, **settings_overrides)
    app = create_app(settings, runner=runner)
    return TestClient(app), app


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_health_and_auth_roles(tmp_path):
    runner = FakeRunner(result=ProcessResult(0, stdout=json.dumps({"packages": [], "count": 0})))
    client, app = make_client(tmp_path, runner)
    # missing
    assert client.post("/api/v1/updates/check").status_code == 401
    # invalid
    assert client.post("/api/v1/updates/check", headers=auth("nope")).status_code == 401
    # reader forbidden
    res = client.post("/api/v1/updates/check", headers=auth(READER))
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "forbidden"


def test_updates_check_202_and_poll(tmp_path):
    payload = {"packages": [{"name": "foo", "current": "1.0", "candidate": "1.1"}], "count": 1}
    runner = FakeRunner(result=ProcessResult(0, stdout=json.dumps(payload)))
    client, app = make_client(tmp_path, runner)

    res = client.post("/api/v1/updates/check", headers=auth(ADMIN))
    assert res.status_code == 202
    body = res.json()
    assert body["kind"] == "update_check"
    assert body["status"] in ("queued", "running", "succeeded")
    assert "poll_url" in body
    assert body["poll_url"] == f"/api/v1/jobs/{body['id']}"
    # poll until done
    job_id = body["id"]
    for _ in range(50):
        r = client.get(f"/api/v1/jobs/{job_id}", headers=auth(ADMIN))
        assert r.status_code == 200
        if r.json()["status"] in ("succeeded", "failed"):
            break
        import time
        time.sleep(0.05)
    final = client.get(f"/api/v1/jobs/{job_id}", headers=auth(ADMIN)).json()
    assert final["status"] == "succeeded"
    assert final["result"]["count"] == 1
    assert final["result"]["packages"][0]["name"] == "foo"
    # sudo prefix proof
    assert runner.calls[0][0][0] == "/usr/bin/sudo"


def test_updates_apply_output_reboot(tmp_path):
    payload = {"reboot_required": True, "output": "done", "output_truncated": False}
    runner = FakeRunner(result=ProcessResult(0, stdout=json.dumps(payload)))
    client, app = make_client(tmp_path, runner)

    res = client.post("/api/v1/updates/apply", headers=auth(ADMIN))
    assert res.status_code == 202
    job_id = res.json()["id"]
    import time
    for _ in range(50):
        r = client.get(f"/api/v1/jobs/{job_id}", headers=auth(ADMIN))
        if r.json()["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    final = client.get(f"/api/v1/jobs/{job_id}", headers=auth(ADMIN)).json()
    assert final["status"] == "succeeded"
    assert final["result"]["reboot_required"] is True
    assert final["output"] == "done"


def test_job_polling_failure(tmp_path):
    runner = FakeRunner(result=ProcessResult(1, stdout="", stderr="boom"))
    client, app = make_client(tmp_path, runner)

    res = client.post("/api/v1/updates/check", headers=auth(ADMIN))
    job_id = res.json()["id"]
    import time
    for _ in range(50):
        r = client.get(f"/api/v1/jobs/{job_id}", headers=auth(ADMIN))
        if r.json()["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    final = client.get(f"/api/v1/jobs/{job_id}", headers=auth(ADMIN)).json()
    assert final["status"] == "failed"
    assert final["error_code"] == "helper_failed"


def test_job_unknown_404(tmp_path):
    runner = FakeRunner(result=ProcessResult(0, stdout="{}"))
    client, app = make_client(tmp_path, runner)
    res = client.get("/api/v1/jobs/does-not-exist", headers=auth(ADMIN))
    assert res.status_code == 404


def test_job_conflict_power_pending(tmp_path):
    # schedule a power action (pending) then job check should conflict
    runner = FakeRunner(result=ProcessResult(0, stdout=json.dumps({"scheduled": True})))
    client, app = make_client(tmp_path, runner)
    # schedule power
    r = client.post(
        "/api/v1/power-actions",
        headers=auth(ADMIN),
        json={"action": "reboot", "delay_seconds": 60, "confirmation": "reboot"},
    )
    assert r.status_code == 202
    # now job check conflicts
    runner2 = FakeRunner(result=ProcessResult(0, stdout="{}"))
    # reuse same runner? job manager uses same runner; okay
    res = client.post("/api/v1/updates/check", headers=auth(ADMIN))
    assert res.status_code == 409


def test_power_action_conflict_job_active(tmp_path):
    runner = FakeRunner(result=ProcessResult(0, stdout=json.dumps({"scheduled": True})))
    client, app = make_client(tmp_path, runner)
    from linux_monitor.main import ensure_operation_resources
    ensure_operation_resources(app)
    app.state.job_manager._active_job_id = "existing-active"
    res = client.post(
        "/api/v1/power-actions",
        headers=auth(ADMIN),
        json={"action": "reboot", "delay_seconds": 60, "confirmation": "reboot"},
    )
    assert res.status_code == 409


def test_power_create_invalid_body_422(tmp_path):
    runner = FakeRunner(result=ProcessResult(0, stdout="{}"))
    client, app = make_client(tmp_path, runner)
    # delay too small
    res = client.post(
        "/api/v1/power-actions",
        headers=auth(ADMIN),
        json={"action": "reboot", "delay_seconds": 5, "confirmation": "reboot"},
    )
    assert res.status_code == 422
    # exact confirmation
    res = client.post(
        "/api/v1/power-actions",
        headers=auth(ADMIN),
        json={"action": "reboot", "delay_seconds": 60, "confirmation": "shutdown"},
    )
    assert res.status_code == 422
    # invalid action
    res = client.post(
        "/api/v1/power-actions",
        headers=auth(ADMIN),
        json={"action": "halt", "delay_seconds": 60, "confirmation": "halt"},
    )
    assert res.status_code == 422


def test_power_create_success_and_get(tmp_path):
    runner = FakeRunner(result=ProcessResult(0, stdout=json.dumps({"scheduled": True})))
    client, app = make_client(tmp_path, runner)
    res = client.post(
        "/api/v1/power-actions",
        headers=auth(ADMIN),
        json={"action": "shutdown", "delay_seconds": 120, "confirmation": "shutdown"},
    )
    assert res.status_code == 202
    body = res.json()
    assert body["action"] == "shutdown"
    assert body["status"] == "pending"
    assert body["cancellable"] is True
    assert "scheduled_for" in body
    action_id = body["id"]
    # default delay
    # get
    g = client.get(f"/api/v1/power-actions/{action_id}", headers=auth(ADMIN))
    assert g.status_code == 200
    assert g.json()["id"] == action_id


def test_power_default_delay(tmp_path):
    runner = FakeRunner(result=ProcessResult(0, stdout=json.dumps({"scheduled": True})))
    client, app = make_client(tmp_path, runner)
    res = client.post(
        "/api/v1/power-actions",
        headers=auth(ADMIN),
        json={"action": "reboot", "confirmation": "reboot"},
    )
    assert res.status_code == 202
    assert runner.calls[0][0] == ["/usr/bin/sudo", "-n", "/helper", "power-schedule", "reboot", "60"]


def test_power_cancel(tmp_path):
    runner = FakeRunner(results=[
        ProcessResult(0, stdout=json.dumps({"scheduled": True})),
        ProcessResult(0, stdout=json.dumps({"cancelled": True})),
    ])
    client, app = make_client(tmp_path, runner)
    r1 = client.post(
        "/api/v1/power-actions",
        headers=auth(ADMIN),
        json={"action": "reboot", "delay_seconds": 60, "confirmation": "reboot"},
    )
    action_id = r1.json()["id"]
    c = client.delete(f"/api/v1/power-actions/{action_id}", headers=auth(ADMIN))
    assert c.status_code == 200
    assert c.json()["status"] == "cancelled"
    c2 = client.delete(f"/api/v1/power-actions/{action_id}", headers=auth(ADMIN))
    assert c2.status_code == 409


def test_power_unknown_404(tmp_path):
    runner = FakeRunner(result=ProcessResult(0, stdout="{}"))
    client, app = make_client(tmp_path, runner)
    assert client.get("/api/v1/power-actions/nope", headers=auth(ADMIN)).status_code == 404
    assert client.delete("/api/v1/power-actions/nope", headers=auth(ADMIN)).status_code == 404


def test_power_cancellation_closed(tmp_path):
    runner = FakeRunner(result=ProcessResult(0, stdout=json.dumps({"scheduled": True})))
    client, app = make_client(tmp_path, runner)
    r1 = client.post(
        "/api/v1/power-actions",
        headers=auth(ADMIN),
        json={"action": "reboot", "delay_seconds": 60, "confirmation": "reboot"},
    )
    action_id = r1.json()["id"]
    # mark scheduled_for in past
    store = app.state.store
    from linux_monitor.operations import utcnow
    from datetime import timedelta
    action = store.get_power_action(action_id)
    store.update_power_action(action_id, scheduled_for=utcnow() - timedelta(seconds=10))
    # cancel should conflict 409
    c = client.delete(f"/api/v1/power-actions/{action_id}", headers=auth(ADMIN))
    assert c.status_code == 409
    # cancellable false
    g = client.get(f"/api/v1/power-actions/{action_id}", headers=auth(ADMIN))
    assert g.json()["cancellable"] is False


def test_privileged_helper_failure_503(tmp_path):
    runner = FakeRunner(result=ProcessResult(1, stdout="", stderr="helper boom"))
    client, app = make_client(tmp_path, runner)
    res = client.post(
        "/api/v1/power-actions",
        headers=auth(ADMIN),
        json={"action": "reboot", "delay_seconds": 60, "confirmation": "reboot"},
    )
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "helper_failed"


def test_no_real_commands_execute(tmp_path):
    runner = FakeRunner(result=ProcessResult(0, stdout=json.dumps({"packages": [], "count": 0})))
    client, app = make_client(tmp_path, runner)
    client.post("/api/v1/updates/check", headers=auth(ADMIN))
    # runner recorded call but did not execute real commands
    assert len(runner.calls) >= 1
    # Ensure no subprocess module used; calls are just tuples
    for call in runner.calls:
        assert isinstance(call[0], list)


def test_db_lifecycle(tmp_path):
    runner = FakeRunner(result=ProcessResult(0, stdout=json.dumps({"packages": [], "count": 0})))
    db = tmp_path / "life.db"
    settings = make_settings(tmp_path, database_path=str(db))
    app = create_app(settings, runner=runner)
    with TestClient(app) as client:
        res = client.post("/api/v1/updates/check", headers=auth(ADMIN))
        job_id = res.json()["id"]
        import time
        for _ in range(50):
            r = client.get(f"/api/v1/jobs/{job_id}", headers=auth(ADMIN))
            if r.json()["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.05)
    # reopen store
    store = StateStore(db)
    job = store.get_job(job_id)
    assert job is not None
    assert job.status == "succeeded"
    store.close()


def test_reader_forbidden_power(tmp_path):
    runner = FakeRunner(result=ProcessResult(0, stdout="{}"))
    client, app = make_client(tmp_path, runner)
    res = client.get("/api/v1/power-actions/abc", headers=auth(READER))
    assert res.status_code == 403
