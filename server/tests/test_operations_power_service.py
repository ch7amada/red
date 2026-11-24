import asyncio
import json

import pytest

from linux_monitor.operations import PowerService, StateStore, ProcessResult
from linux_monitor.operations.errors import ConflictError, InvalidInputError, NotFoundError


class FakeRunner:
    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc
        self.calls = []

    async def run(self, argv, *, timeout, env=None):
        self.calls.append((list(argv), timeout, env))
        if self.exc is not None:
            raise self.exc
        return self.result


@pytest.fixture
def store(tmp_path):
    return StateStore(tmp_path / "power.db")


def test_power_validation(store):
    runner = FakeRunner(result=ProcessResult(0, stdout="{}"))
    ps = PowerService(store, runner, "/helper", use_sudo=False)
    with pytest.raises(InvalidInputError):
        asyncio.get_event_loop().run_until_complete(
            ps.schedule("reboot", 5, confirmed=True, credential_identity="admin", correlation_id="c1")
        )
    with pytest.raises(InvalidInputError):
        asyncio.get_event_loop().run_until_complete(
            ps.schedule("reboot", 60, confirmed=False, credential_identity="admin", correlation_id="c2")
        )
    with pytest.raises(InvalidInputError):
        asyncio.get_event_loop().run_until_complete(
            ps.schedule("halt", 60, confirmed=True, credential_identity="admin", correlation_id="c3")
        )


def test_power_schedule_success_and_one_pending(store):
    runner = FakeRunner(result=ProcessResult(0, stdout=json.dumps({"scheduled": True})))
    ps = PowerService(store, runner, "/helper", use_sudo=False)
    action = asyncio.get_event_loop().run_until_complete(
        ps.schedule("reboot", 60, confirmed=True, credential_identity="admin", correlation_id="c1")
    )
    assert action.status == "pending"
    assert runner.calls[0][0] == ["/helper", "power-schedule", "reboot", "60"]
    # second pending conflict
    with pytest.raises(ConflictError):
        asyncio.get_event_loop().run_until_complete(
            ps.schedule("shutdown", 120, confirmed=True, credential_identity="admin", correlation_id="c2")
        )


def test_power_cancel(store):
    runner = FakeRunner(result=ProcessResult(0, stdout=json.dumps({"cancelled": True})))
    ps = PowerService(store, runner, "/helper", use_sudo=False)
    action = asyncio.get_event_loop().run_until_complete(
        ps.schedule("reboot", 60, confirmed=True, credential_identity="admin", correlation_id="c1")
    )
    cancelled = asyncio.get_event_loop().run_until_complete(
        ps.cancel(action.id, credential_identity="admin")
    )
    assert cancelled.status == "cancelled"


def test_power_cancel_not_found_and_not_pending(store):
    runner = FakeRunner(result=ProcessResult(0, stdout="{}"))
    ps = PowerService(store, runner, "/helper", use_sudo=False)
    with pytest.raises(NotFoundError):
        asyncio.get_event_loop().run_until_complete(ps.cancel("missing", credential_identity="admin"))
    # create and cancel once
    runner2 = FakeRunner(result=ProcessResult(0, stdout="{}"))
    ps2 = PowerService(store, runner2, "/helper", use_sudo=False)
    action = asyncio.get_event_loop().run_until_complete(
        ps2.schedule("reboot", 60, confirmed=True, credential_identity="admin", correlation_id="c2")
    )
    asyncio.get_event_loop().run_until_complete(ps2.cancel(action.id, credential_identity="admin"))
    with pytest.raises(ConflictError):
        asyncio.get_event_loop().run_until_complete(ps2.cancel(action.id, credential_identity="admin"))


def test_power_apt_conflict(store):
    class JM:
        def has_active_apt(self):
            return True
    runner = FakeRunner(result=ProcessResult(0, stdout="{}"))
    ps = PowerService(store, runner, "/helper", use_sudo=False, job_manager=JM())
    with pytest.raises(ConflictError):
        asyncio.get_event_loop().run_until_complete(
            ps.schedule("reboot", 60, confirmed=True, credential_identity="admin", correlation_id="c1")
        )


def test_power_persists(store, tmp_path):
    runner = FakeRunner(result=ProcessResult(0, stdout="{}"))
    ps = PowerService(store, runner, "/helper", use_sudo=False)
    action = asyncio.get_event_loop().run_until_complete(
        ps.schedule("shutdown", 300, confirmed=True, credential_identity="admin", correlation_id="c1")
    )
    store.close()
    store2 = StateStore(tmp_path / "power.db")
    assert store2.get_power_action(action.id).status == "pending"