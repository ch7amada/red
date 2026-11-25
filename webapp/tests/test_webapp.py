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


def _job(job_id="11111111-2222-3333-4444-555555555555", status="succeeded", **extra):
    base = {
        "id": job_id,
        "kind": "update_check",
        "status": status,
        "created_at": "2026-01-01T00:00:00Z",
        "started_at": "2026-01-01T00:00:00Z",
        "finished_at": "2026-01-01T00:00:01Z",
        "result": {"packages": [{"name": "foo", "current": "1.0", "candidate": "1.1"}], "count": 1},
        "output": "done",
        "output_truncated": False,
        "error_code": None,
        "error_message": None,
        "poll_url": f"/api/v1/jobs/{job_id}",
    }
    base.update(extra)
    return base


def _power(action_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", status="pending", cancellable=True, action="reboot"):
    return {
        "id": action_id,
        "action": action,
        "status": status,
        "created_at": "2026-01-01T00:00:00Z",
        "scheduled_for": "2026-01-01T00:01:00Z",
        "cancellable": cancellable,
    }


def test_control_requires_session():
    async def handler(request):
        return httpx.Response(200, json=_snapshot())

    client = _make(handler)
    r = client.get("/control", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location") == "/connect"


def test_control_reader_view():
    async def handler(request):
        if request.url.path == "/api/v1/system":
            return httpx.Response(200, json=_snapshot())
        if request.url.path.startswith("/api/v1/jobs/"):
            return httpx.Response(403, json={"error": {"code": "forbidden"}})
        return httpx.Response(404)

    client = _make(handler)
    r = client.post("/connect", data={"token": "t" * 32}, headers={"origin": "http://testserver"}, follow_redirects=False)
    cookies = r.cookies
    r2 = client.get("/control", cookies=cookies, follow_redirects=False)
    assert r2.status_code == 200
    assert "Reader access" in r2.text or "reader" in r2.text.lower()


def test_control_admin_view():
    async def handler(request):
        if request.url.path == "/api/v1/system":
            return httpx.Response(200, json=_snapshot())
        if request.url.path.startswith("/api/v1/jobs/"):
            return httpx.Response(404, json={"error": {"code": "not_found"}})
        return httpx.Response(404)

    client = _make(handler)
    r = client.post("/connect", data={"token": "t" * 32}, headers={"origin": "http://testserver"}, follow_redirects=False)
    cookies = r.cookies
    r2 = client.get("/control", cookies=cookies, follow_redirects=False)
    assert r2.status_code == 200
    assert "Check for updates" in r2.text


def test_control_unavailable():
    async def handler(request):
        if request.url.path == "/api/v1/system":
            return httpx.Response(200, json=_snapshot())
        if request.url.path.startswith("/api/v1/jobs/"):
            raise httpx.ConnectError("boom")
        return httpx.Response(404)

    client = _make(handler)
    r = client.post("/connect", data={"token": "t" * 32}, headers={"origin": "http://testserver"}, follow_redirects=False)
    cookies = r.cookies
    r2 = client.get("/control", cookies=cookies, follow_redirects=False)
    assert r2.status_code == 200
    assert "unavailable" in r2.text.lower()


def test_control_401_revokes():
    calls = {"n": 0}

    async def handler(request):
        if request.url.path == "/api/v1/system":
            return httpx.Response(200, json=_snapshot())
        if request.url.path.startswith("/api/v1/jobs/"):
            calls["n"] += 1
            return httpx.Response(401, json={"error": {"code": "unauthorized"}})
        return httpx.Response(404)

    client = _make(handler)
    r = client.post("/connect", data={"token": "t" * 32}, headers={"origin": "http://testserver"}, follow_redirects=False)
    cookies = r.cookies
    r2 = client.get("/control", cookies=cookies, follow_redirects=False)
    assert r2.status_code == 303
    assert r2.headers.get("location") == "/connect"
    # session revoked
    r3 = client.get("/fragments/overview", cookies=cookies, headers={"HX-Request": "true"}, follow_redirects=False)
    assert r3.status_code == 401


def test_updates_check_htmx():
    async def handler(request):
        if request.url.path == "/api/v1/system":
            return httpx.Response(200, json=_snapshot())
        if request.url.path == "/api/v1/jobs/00000000-0000-0000-0000-000000000000":
            return httpx.Response(404, json={"error": {"code": "not_found"}})
        if request.url.path == "/api/v1/updates/check":
            return httpx.Response(202, json=_job(status="running"))
        if request.url.path.startswith("/api/v1/jobs/"):
            return httpx.Response(200, json=_job(status="running"))
        return httpx.Response(404)

    client = _make(handler)
    r = client.post("/connect", data={"token": "t" * 32}, headers={"origin": "http://testserver"}, follow_redirects=False)
    cookies = r.cookies
    r2 = client.post("/control/updates/check", cookies=cookies, headers={"HX-Request": "true", "origin": "http://testserver"}, follow_redirects=False)
    assert r2.status_code == 200
    assert "running" in r2.text


def test_updates_check_origin_rejected():
    async def handler(request):
        if request.url.path == "/api/v1/system":
            return httpx.Response(200, json=_snapshot())
        if request.url.path.startswith("/api/v1/jobs/"):
            return httpx.Response(404, json={"error": {"code": "not_found"}})
        return httpx.Response(200, json=_snapshot())

    client = _make(handler)
    r = client.post("/connect", data={"token": "t" * 32}, headers={"origin": "http://testserver"}, follow_redirects=False)
    cookies = r.cookies
    r2 = client.post("/control/updates/check", cookies=cookies, headers={"HX-Request": "true"}, follow_redirects=False)
    assert r2.status_code == 403


def test_updates_check_conflict_htmx():
    async def handler(request):
        if request.url.path == "/api/v1/system":
            return httpx.Response(200, json=_snapshot())
        if request.url.path == "/api/v1/jobs/00000000-0000-0000-0000-000000000000":
            return httpx.Response(404, json={"error": {"code": "not_found"}})
        if request.url.path == "/api/v1/updates/check":
            return httpx.Response(409, json={"error": {"code": "conflict", "message": "busy"}})
        return httpx.Response(404)

    client = _make(handler)
    r = client.post("/connect", data={"token": "t" * 32}, headers={"origin": "http://testserver"}, follow_redirects=False)
    cookies = r.cookies
    r2 = client.post("/control/updates/check", cookies=cookies, headers={"HX-Request": "true", "origin": "http://testserver"}, follow_redirects=False)
    assert r2.status_code == 200
    assert "conflict" in r2.text.lower() or "busy" in r2.text.lower()


def test_apply_confirmation_required():
    async def handler(request):
        if request.url.path == "/api/v1/system":
            return httpx.Response(200, json=_snapshot())
        if request.url.path == "/api/v1/jobs/00000000-0000-0000-0000-000000000000":
            return httpx.Response(404, json={"error": {"code": "not_found"}})
        return httpx.Response(404)

    client = _make(handler)
    r = client.post("/connect", data={"token": "t" * 32}, headers={"origin": "http://testserver"}, follow_redirects=False)
    cookies = r.cookies
    # HTMX without confirm
    r2 = client.post("/control/updates/apply", data={}, cookies=cookies, headers={"HX-Request": "true", "origin": "http://testserver"}, follow_redirects=False)
    assert r2.status_code == 200
    assert "Confirmation required" in r2.text


def test_power_create_validation():
    async def handler(request):
        if request.url.path == "/api/v1/system":
            return httpx.Response(200, json=_snapshot())
        if request.url.path == "/api/v1/jobs/00000000-0000-0000-0000-000000000000":
            return httpx.Response(404, json={"error": {"code": "not_found"}})
        return httpx.Response(404)

    client = _make(handler)
    r = client.post("/connect", data={"token": "t" * 32}, headers={"origin": "http://testserver"}, follow_redirects=False)
    cookies = r.cookies
    # bad delay
    r2 = client.post("/control/power-actions", data={"action": "reboot", "delay_seconds": "5", "confirmation": "reboot"}, cookies=cookies, headers={"HX-Request": "true", "origin": "http://testserver"}, follow_redirects=False)
    assert r2.status_code == 200
    assert "Delay must be" in r2.text
    # bad confirmation
    r3 = client.post("/control/power-actions", data={"action": "reboot", "delay_seconds": "60", "confirmation": "shutdown"}, cookies=cookies, headers={"HX-Request": "true", "origin": "http://testserver"}, follow_redirects=False)
    assert r3.status_code == 200
    assert "Confirmation must" in r3.text


def test_power_create_and_poll():
    async def handler(request):
        if request.url.path == "/api/v1/system":
            return httpx.Response(200, json=_snapshot())
        if request.url.path == "/api/v1/jobs/00000000-0000-0000-0000-000000000000":
            return httpx.Response(404, json={"error": {"code": "not_found"}})
        if request.url.path == "/api/v1/power-actions" and request.method == "POST":
            return httpx.Response(202, json=_power())
        if request.url.path.startswith("/api/v1/power-actions/"):
            return httpx.Response(200, json=_power())
        return httpx.Response(404)

    client = _make(handler)
    r = client.post("/connect", data={"token": "t" * 32}, headers={"origin": "http://testserver"}, follow_redirects=False)
    cookies = r.cookies
    r2 = client.post("/control/power-actions", data={"action": "reboot", "delay_seconds": "60", "confirmation": "reboot"}, cookies=cookies, headers={"HX-Request": "true", "origin": "http://testserver"}, follow_redirects=False)
    assert r2.status_code == 200
    assert "reboot" in r2.text.lower()
    r3 = client.get("/control/power-actions/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", cookies=cookies, headers={"HX-Request": "true"}, follow_redirects=False)
    assert r3.status_code == 200
    assert "pending" in r3.text


def test_power_cancel():
    calls = {"n": 0}

    async def handler(request):
        if request.url.path == "/api/v1/system":
            return httpx.Response(200, json=_snapshot())
        if request.url.path == "/api/v1/jobs/00000000-0000-0000-0000-000000000000":
            return httpx.Response(404, json={"error": {"code": "not_found"}})
        if request.url.path == "/api/v1/power-actions" and request.method == "POST":
            return httpx.Response(202, json=_power())
        if request.url.path == "/api/v1/power-actions/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" and request.method == "DELETE":
            calls["n"] += 1
            return httpx.Response(200, json=_power(status="cancelled", cancellable=False))
        if request.url.path.startswith("/api/v1/power-actions/"):
            return httpx.Response(200, json=_power())
        return httpx.Response(404)

    client = _make(handler)
    r = client.post("/connect", data={"token": "t" * 32}, headers={"origin": "http://testserver"}, follow_redirects=False)
    cookies = r.cookies
    client.post("/control/power-actions", data={"action": "reboot", "delay_seconds": "60", "confirmation": "reboot"}, cookies=cookies, headers={"HX-Request": "true", "origin": "http://testserver"}, follow_redirects=False)
    r2 = client.post("/control/power-actions/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/cancel", cookies=cookies, headers={"HX-Request": "true", "origin": "http://testserver"}, follow_redirects=False)
    assert r2.status_code == 200
    assert "cancelled" in r2.text


def test_overview_503_hx_reswap():
    calls = {"n": 0}

    async def handler(request):
        if request.url.path == "/api/v1/system":
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(200, json=_snapshot())
            raise httpx.ConnectError("boom")

    client = _make(handler)
    r = client.post("/connect", data={"token": "t" * 32}, headers={"origin": "http://testserver"}, follow_redirects=False)
    cookies = r.cookies
    r2 = client.get("/fragments/overview", cookies=cookies, headers={"HX-Request": "true"}, follow_redirects=False)
    assert r2.status_code == 200
    assert r2.headers.get("hx-reswap") == "innerHTML"
    assert "unavailable" in r2.text.lower()
