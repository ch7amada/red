import httpx
import pytest
from fastapi.testclient import TestClient

from app import Settings, create_app


def _snapshot() -> dict:
    return {
        "schema_version": "1.0",
        "collected_at": "2026-01-01T00:00:00Z",
        "hostname": "test-host",
        "os": {"name": "Linux", "version": "1", "kernel": "k", "architecture": "x86_64"},
        "uptime_seconds": 3661.0,
        "uptime_status": {"status": "ok", "error": None},
        "cpu": {"status": "ok", "error": None, "utilization_pct": 12.5, "load_1m": 0.1, "load_5m": 0.2, "load_15m": 0.3},
        "memory": {"status": "ok", "error": None, "total_bytes": 1000, "used_bytes": 400, "available_bytes": 600, "used_percent": 40.0},
        "swap": {"status": "ok", "error": None, "total_bytes": 0, "used_bytes": 0, "free_bytes": 0, "used_percent": 0.0},
        "filesystems": [],
        "filesystems_status": {"status": "ok", "error": None},
        "network": [],
        "network_status": {"status": "ok", "error": None},
        "gpus": [],
        "gpu_status": {"status": "ok", "error": None},
    }


def _make(handler):
    transport = httpx.MockTransport(handler)
    upstream = httpx.AsyncClient(transport=transport, base_url="http://upstream", follow_redirects=False, trust_env=False)
    return TestClient(create_app(Settings(upstream_url="http://upstream"), upstream=upstream))


def test_connect_success_sets_session_and_renders():
    async def handler(request):
        assert request.headers["authorization"] == "Bearer " + "t" * 32
        return httpx.Response(200, json=_snapshot())

    client = _make(handler)
    r = client.post("/connect", data={"token": "t" * 32}, headers={"origin": "http://testserver"}, follow_redirects=False)
    assert r.status_code == 303
    assert "lm_session" in r.cookies
    r2 = client.get("/fragments/overview", cookies=r.cookies, headers={"HX-Request": "true"}, follow_redirects=False)
    assert r2.status_code == 200
    assert "test-host" in r2.text
    assert "no-store" in r2.headers.get("cache-control", "")


def test_connect_invalid_credentials():
    async def handler(request):
        return httpx.Response(401, json={"error": {"code": "unauthorized"}})

    client = _make(handler)
    r = client.post("/connect", data={"token": "t" * 32}, headers={"origin": "http://testserver"}, follow_redirects=False)
    assert r.status_code == 401
    assert "Invalid or unauthorized" in r.text
    assert "lm_session" not in r.cookies


def test_connect_unavailable():
    async def handler(request):
        raise httpx.ConnectError("boom")

    client = _make(handler)
    r = client.post("/connect", data={"token": "t" * 32}, headers={"origin": "http://testserver"}, follow_redirects=False)
    assert r.status_code == 503
    assert "unavailable" in r.text.lower()


def test_origin_rejected():
    async def handler(request):
        return httpx.Response(200, json=_snapshot())

    client = _make(handler)
    r = client.post("/connect", data={"token": "t" * 32})
    assert r.status_code == 403


def test_htmx_session_expiry_redirect():
    async def handler(request):
        return httpx.Response(200, json=_snapshot())

    client = _make(handler)
    r = client.get("/fragments/overview", headers={"HX-Request": "true"})
    assert r.status_code == 401
    assert r.headers.get("hx-redirect") == "/connect"


def test_normal_session_expiry_redirect():
    async def handler(request):
        return httpx.Response(200, json=_snapshot())

    client = _make(handler)
    r = client.get("/fragments/overview", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location") == "/connect"


def test_logout_revokes_session():
    async def handler(request):
        return httpx.Response(200, json=_snapshot())

    client = _make(handler)
    r = client.post("/connect", data={"token": "t" * 32}, headers={"origin": "http://testserver"}, follow_redirects=False)
    cookies = r.cookies
    r2 = client.post("/logout", headers={"origin": "http://testserver"}, cookies=cookies, follow_redirects=False)
    assert r2.status_code == 303
    r3 = client.get("/fragments/overview", cookies=cookies, headers={"HX-Request": "true"}, follow_redirects=False)
    assert r3.status_code == 401


def test_upstream_invalid_after_connect_redirects():
    calls = {"n": 0}

    async def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json=_snapshot())
        return httpx.Response(401, json={"error": {"code": "unauthorized"}})

    client = _make(handler)
    r = client.post("/connect", data={"token": "t" * 32}, headers={"origin": "http://testserver"}, follow_redirects=False)
    cookies = r.cookies
    r2 = client.get("/fragments/overview", cookies=cookies, headers={"HX-Request": "true"}, follow_redirects=False)
    assert r2.status_code == 401
    assert r2.headers.get("hx-redirect") == "/connect"
