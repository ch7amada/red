import os

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from linux_monitor.auth import require_admin
from linux_monitor.config import Settings
from linux_monitor.main import create_app
from linux_monitor.schemas import ComponentStatus, CpuInfo, MemoryInfo, OsInfo, SwapInfo, SystemInfo
from datetime import datetime, timezone


def _fake_system(settings):
    return SystemInfo(
        collected_at=datetime.now(timezone.utc),
        hostname="test-host",
        os=OsInfo(name="Linux", version="1", kernel="k", architecture="x86_64"),
        uptime_seconds=1.0,
        uptime_status=ComponentStatus(status="ok"),
        cpu=CpuInfo(status="ok"),
        memory=MemoryInfo(status="ok"),
        swap=SwapInfo(status="ok"),
        filesystems=[],
        filesystems_status=ComponentStatus(status="ok"),
        network=[],
        network_status=ComponentStatus(status="ok"),
        gpus=[],
        gpu_status=ComponentStatus(status="ok"),
    )


@pytest.fixture(autouse=True)
def mock_system_collector(monkeypatch):
    monkeypatch.setattr("linux_monitor.main.collect_system", _fake_system)


def make_client(reader="r" * 40, admin="a" * 40, **kwargs):
    settings = Settings(reader_token=reader, admin_token=admin, environment="test", **kwargs)
    return TestClient(create_app(settings))


def test_health_live_exact():
    client = make_client()
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_system_requires_auth():
    client = make_client()
    response = client.get("/api/v1/system")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "unauthorized"
    assert isinstance(body["error"]["request_id"], str)


def test_reader_token_works():
    client = make_client()
    response = client.get("/api/v1/system", headers={"Authorization": "Bearer " + "r" * 40})
    assert response.status_code == 200


def test_admin_token_works():
    client = make_client()
    response = client.get("/api/v1/system", headers={"Authorization": "Bearer " + "a" * 40})
    assert response.status_code == 200


def test_invalid_token_401():
    client = make_client()
    response = client.get("/api/v1/system", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_auth_throttle():
    client = make_client()
    for _ in range(5):
        response = client.get("/api/v1/system", headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401
    response = client.get("/api/v1/system", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_requests"


def test_docs_disabled_by_default():
    client = make_client()
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_docs_enabled_opt_in():
    client = make_client(docs_enabled=True)
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_reader_token_forbidden_for_admin_protected():
    settings = Settings(reader_token="r" * 40, admin_token="a" * 40, environment="test")
    app = create_app(settings)

    @app.get("/_test/admin-only")
    def admin_only(_identity: str = Depends(require_admin)):
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/_test/admin-only", headers={"Authorization": "Bearer " + "r" * 40})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_production_missing_tokens_fail_fast(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("READER_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(Exception):
        create_app()