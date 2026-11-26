import pytest
import time

from linux_monitor.config import Settings
from linux_monitor.collectors import llama_cpp


def _settings():
    return Settings(
        reader_token="r" * 40,
        admin_token="a" * 40,
        environment="test",
        llama_cpp_url="http://127.0.0.1:8081",
    )


def test_router_catalog_and_active_context(monkeypatch):
    def fake(url, headers, deadline):
        if url.endswith("/health"):
            return 200, {"status": "ok"}
        if url.endswith("/models"):
            return 200, {
                "data": [
                    {
                        "id": "router-model",
                        "status": {"value": "loaded"},
                        "context_length": 262144,
                        "meta": {"n_ctx": 32768, "n_ctx_train": 262144},
                    },
                    {
                        "id": "other-model",
                        "status": {"value": "unloaded"},
                        "context_length": 131072,
                        "meta": {"n_ctx": 4096, "n_ctx_train": 131072},
                    },
                ]
            }
        if "/props?" in url:
            assert "autoload=false" in url
            assert "model=router-model" in url
            return 200, {
                "is_sleeping": False,
                "default_generation_settings": {"n_ctx": 8192},
                "total_slots": 2,
            }
        raise AssertionError(url)

    monkeypatch.setattr(llama_cpp, "_get_json", fake)
    info = llama_cpp.collect_llama_cpp(_settings())
    assert info.status == "running"
    assert info.models[0].id == "router-model"
    assert info.models[0].status == "loaded"
    assert info.models[0].context_tokens == 8192
    assert info.models[0].training_context_tokens == 262144
    assert info.models[0].total_slots == 2
    assert info.models[1].id == "other-model"
    assert info.models[1].status == "unloaded"
    assert info.models[1].training_context_tokens == 131072


def test_direct_sleeping_case(monkeypatch):
    def fake(url, headers, deadline):
        if url.endswith("/health"):
            return 200, {"status": "ok"}
        if url.endswith("/models"):
            return 200, {
                "data": [
                    {
                        "id": "single-model",
                        "context_length": 65536,
                        "meta": {"n_ctx": 4096, "n_ctx_train": 65536},
                    }
                ]
            }
        if url.endswith("/props"):
            return 200, {
                "is_sleeping": True,
                "default_generation_settings": {"n_ctx": 2048},
                "total_slots": 1,
            }
        raise AssertionError(url)

    monkeypatch.setattr(llama_cpp, "_get_json", fake)
    info = llama_cpp.collect_llama_cpp(_settings())
    assert info.status == "running"
    assert len(info.models) == 1
    model = info.models[0]
    assert model.id == "single-model"
    assert model.status == "sleeping"
    assert model.context_tokens == 2048
    assert model.training_context_tokens == 65536
    assert model.total_slots == 1


def test_auth_degrades(monkeypatch):
    def fake(url, headers, deadline):
        if url.endswith("/health"):
            return 200, {"status": "ok"}
        if url.endswith("/models"):
            return 401, {"error": "unauthorized"}
        raise AssertionError(url)

    monkeypatch.setattr(llama_cpp, "_get_json", fake)
    info = llama_cpp.collect_llama_cpp(_settings())
    assert info.status == "running"
    assert info.models == []
    assert info.error is not None
    assert "auth" in info.error.lower()


def test_unreachable_degrades(monkeypatch):
    def fake(url, headers, deadline):
        raise RuntimeError("boom")

    monkeypatch.setattr(llama_cpp, "_get_json", fake)
    info = llama_cpp.collect_llama_cpp(_settings())
    assert info.status == "unavailable"
    assert info.models == []


def test_explicit_no_autoload(monkeypatch):
    seen = {"props": None}

    def fake(url, headers, deadline):
        if url.endswith("/health"):
            return 200, {"status": "ok"}
        if url.endswith("/models"):
            return 200, {
                "data": [
                    {
                        "id": "m/with space",
                        "status": {"value": "loaded"},
                        "context_length": 10,
                        "meta": {},
                    }
                ]
            }
        if "/props?" in url:
            seen["props"] = url
            return 200, {"default_generation_settings": {"n_ctx": 5}, "total_slots": 1}
        raise AssertionError(url)

    monkeypatch.setattr(llama_cpp, "_get_json", fake)
    info = llama_cpp.collect_llama_cpp(_settings())
    assert seen["props"] is not None
    assert "autoload=false" in seen["props"]
    assert info.models[0].context_tokens == 5


def test_catalog_preserves_unknown_and_malformed_statuses(monkeypatch):
    def fake(url, headers, deadline):
        if url.endswith("/health"):
            return 200, {"status": "ok"}
        if url.endswith("/models"):
            return 200, {
                "data": [
                    {"id": "downloading-model", "status": {"value": "downloading"}},
                    {"id": "incomplete-model", "status": {"value": "incomplete"}},
                    {"id": "downloaded-model", "status": {"value": "downloaded"}},
                    {"id": "loaded-model", "status": "loaded"},
                    {"id": "unknown-status", "status": {"value": "bogus"}},
                    {"id": "null-status", "status": None},
                    {"id": "list-status", "status": ["x"]},
                    {"id": "dict-value", "status": {"value": {"x": 1}}},
                    {"id": "missing-status"},
                ]
            }
        # Props may be requested for loaded rows; return empty success.
        if "/props" in url:
            return 200, {}
        raise AssertionError(url)

    monkeypatch.setattr(llama_cpp, "_get_json", fake)
    info = llama_cpp.collect_llama_cpp(_settings())
    assert info.status == "running"
    by_id = {m.id: m.status for m in info.models}
    assert by_id["downloading-model"] == "downloading"
    assert by_id["incomplete-model"] == "incomplete"
    assert by_id["downloaded-model"] == "downloaded"
    assert by_id["loaded-model"] == "loaded"
    assert by_id["unknown-status"] == "unknown"
    assert by_id["null-status"] == "unknown"
    assert by_id["list-status"] == "unknown"
    assert by_id["dict-value"] == "unknown"
    assert by_id["missing-status"] == "loaded"
    assert len(info.models) == 9


def test_health_503_actual_loading(monkeypatch):
    def fake(url, headers, deadline):
        if url.endswith("/health"):
            return 503, {"error": {"message": "Loading model", "type": "unavailable_error", "code": 503}}
        raise AssertionError(url)

    monkeypatch.setattr(llama_cpp, "_get_json", fake)
    info = llama_cpp.collect_llama_cpp(_settings())
    assert info.status == "loading"


def test_health_503_legacy_loading(monkeypatch):
    def fake(url, headers, deadline):
        if url.endswith("/health"):
            return 503, {"status": "loading model"}
        raise AssertionError(url)

    monkeypatch.setattr(llama_cpp, "_get_json", fake)
    info = llama_cpp.collect_llama_cpp(_settings())
    assert info.status == "loading"


def test_health_503_generic_unavailable(monkeypatch):
    def fake(url, headers, deadline):
        if url.endswith("/health"):
            return 503, {"error": "proxy error"}
        raise AssertionError(url)

    monkeypatch.setattr(llama_cpp, "_get_json", fake)
    info = llama_cpp.collect_llama_cpp(_settings())
    assert info.status == "unavailable"


def test_secret_not_forwarded_on_redirect():
    import http.server
    import socketserver
    import threading

    leaked = {"value": False}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/src":
                if self.headers.get("Authorization") == "Bearer secret-token":
                    self.send_response(302)
                    self.send_header("Location", "/dst")
                    self.end_headers()
                    return
                self.send_response(401)
                self.end_headers()
                return
            if self.path == "/dst":
                if self.headers.get("Authorization"):
                    leaked["value"] = True
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok": true}')
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_port
        url = f"http://127.0.0.1:{port}/src"
        status, body = llama_cpp._get_json(url, {"Authorization": "Bearer secret-token"}, __import__("time").monotonic() + 2.0)
        assert status in (301, 302, 303, 307, 308)
        assert leaked["value"] is False
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def test_bare_default_does_not_call_slots(monkeypatch):
    settings = _settings()
    seen = []

    def fake(url, headers, deadline):
        seen.append(url)
        if url.endswith("/health"):
            return 200, {"status": "ok"}
        if url.endswith("/models"):
            return 200, {"data": [{"id": "m"}]}
        if url.endswith("/props"):
            return 200, {"default_generation_settings": {"n_ctx": 4}}
        if "/slots" in url:
            raise AssertionError("slots should not be called by default")
        raise AssertionError(url)

    monkeypatch.setattr(llama_cpp, "_get_json", fake)
    info = llama_cpp.collect_llama_cpp(settings)
    assert info.models[0].slots is None
    assert not any("/slots" in url for url in seen)


@pytest.mark.parametrize("router", [False, True])
def test_context_slots_projection_and_auth(monkeypatch, router):
    settings = Settings(
        reader_token="r" * 40,
        admin_token="a" * 40,
        environment="test",
        llama_cpp_url="http://127.0.0.1:8081",
        llama_cpp_api_key="secret",
    )
    seen = []

    def fake(url, headers, deadline):
        seen.append(url)
        if "/health" in url:
            return 200, {"status": "ok"}
        if "/models" in url:
            if router:
                return 200, {"data": [{"id": "m", "status": {"value": "loaded"}}]}
            return 200, {"data": [{"id": "m"}]}
        if "/props" in url:
            assert headers.get("Authorization") == "Bearer secret"
            assert ("model=m" in url and "autoload=false" in url) == router
            return 200, {
                "is_sleeping": False,
                "default_generation_settings": {"n_ctx": 9},
                "total_slots": 2,
            }
        if "/slots" in url:
            assert headers.get("Authorization") == "Bearer secret"
            assert ("model=m" in url and "autoload=false" in url) == router
            return 200, [
                {"id": 0, "n_ctx": 10, "n_prompt_tokens": 3, "n_past": 99, "n_decoded": 7, "is_processing": True, "prompt": "dummy", "generated": "dummy", "params": {"foo": "bar"}},
                {"id": 1, "n_ctx": 8, "n_prompt_tokens": 0},
                {"id": 2, "n_ctx": 5},
                {"id": 3, "n_ctx": 4, "n_prompt_tokens": -1, "n_past": "x"},
                {"id": "bad", "n_ctx": 4},
                {"id": 4, "n_ctx": 0},
            ]
        raise AssertionError(url)

    monkeypatch.setattr(llama_cpp, "_get_json", fake)
    info = llama_cpp.collect_llama_cpp(settings, include_llama_context=True)
    model = info.models[0]
    assert model.status == "loaded"
    assert model.context_tokens == 9
    assert model.slots is not None
    assert [s.id for s in model.slots] == [0, 1, 2, 3]
    assert model.slots[0].used_tokens == 3
    assert model.slots[0].remaining_tokens == 7
    assert model.slots[0].is_processing is True
    assert set(model.slots[0].model_dump().keys()) == {"id", "context_tokens", "used_tokens", "remaining_tokens", "is_processing"}
    assert model.slots[0].model_dump() == {"id": 0, "context_tokens": 10, "used_tokens": 3, "remaining_tokens": 7, "is_processing": True}
    assert model.slots[1].used_tokens == 0
    assert model.slots[1].remaining_tokens == 8
    assert model.slots[2].used_tokens is None
    assert model.slots[2].remaining_tokens is None
    assert model.slots[3].used_tokens is None
    assert model.slots[3].remaining_tokens is None
    assert any("/slots" in url for url in seen)
    info2 = llama_cpp.collect_llama_cpp(settings, include_llama_context=False)
    assert info2.models[0].slots is None


def test_context_slots_empty_malformed_disabled_sleeping(monkeypatch):
    settings = _settings()

    def empty_fake(url, headers, deadline):
        if url.endswith("/health"):
            return 200, {"status": "ok"}
        if url.endswith("/models"):
            return 200, {"data": [{"id": "m"}]}
        if url.endswith("/props"):
            return 200, {"default_generation_settings": {"n_ctx": 4}}
        if url.endswith("/slots"):
            return 200, []
        raise AssertionError(url)

    monkeypatch.setattr(llama_cpp, "_get_json", empty_fake)
    info = llama_cpp.collect_llama_cpp(settings, include_llama_context=True)
    assert info.models[0].slots == []

    def malformed_fake(url, headers, deadline):
        if url.endswith("/health"):
            return 200, {"status": "ok"}
        if url.endswith("/models"):
            return 200, {"data": [{"id": "m"}]}
        if url.endswith("/props"):
            return 200, {"default_generation_settings": {"n_ctx": 4}}
        if url.endswith("/slots"):
            return 200, [{"bad": True}, {"id": 1}]
        raise AssertionError(url)

    monkeypatch.setattr(llama_cpp, "_get_json", malformed_fake)
    info = llama_cpp.collect_llama_cpp(settings, include_llama_context=True)
    assert info.models[0].slots is None

    def disabled_fake(url, headers, deadline):
        if url.endswith("/health"):
            return 200, {"status": "ok"}
        if url.endswith("/models"):
            return 200, {"data": [{"id": "m"}]}
        if url.endswith("/props"):
            return 200, {"default_generation_settings": {"n_ctx": 4}}
        if url.endswith("/slots"):
            return 404, None
        raise AssertionError(url)

    monkeypatch.setattr(llama_cpp, "_get_json", disabled_fake)
    info = llama_cpp.collect_llama_cpp(settings, include_llama_context=True)
    assert info.models[0].slots is None

    def sleeping_fake(url, headers, deadline):
        if url.endswith("/health"):
            return 200, {"status": "ok"}
        if url.endswith("/models"):
            return 200, {"data": [{"id": "m"}]}
        if url.endswith("/props"):
            return 200, {"is_sleeping": True, "default_generation_settings": {"n_ctx": 4}}
        if url.endswith("/slots"):
            raise AssertionError("slots should not be sampled")
        raise AssertionError(url)

    monkeypatch.setattr(llama_cpp, "_get_json", sleeping_fake)
    info = llama_cpp.collect_llama_cpp(settings, include_llama_context=True)
    assert info.models[0].status == "sleeping"
    assert info.models[0].slots is None
