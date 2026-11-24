from fastapi.testclient import TestClient

from linux_monitor.config import Settings
from linux_monitor.main import create_app


def make_client():
    settings = Settings(reader_token="r" * 40, admin_token="a" * 40, environment="test", cpu_sample_seconds=0.01)
    return TestClient(create_app(settings))


def test_cpu_failure_degrades(monkeypatch):
    def boom(interval=None):
        raise RuntimeError("cpu boom")

    monkeypatch.setattr("linux_monitor.collectors.cpu.psutil.cpu_percent", boom)
    client = make_client()
    response = client.get("/api/v1/system", headers={"Authorization": "Bearer " + "r" * 40})
    assert response.status_code == 200
    data = response.json()
    assert data["cpu"]["status"] == "error"
    assert data["cpu"]["utilization_pct"] is None
    assert data["cpu"]["error"] == "collection failed"


def test_memory_failure_degrades(monkeypatch):
    monkeypatch.setattr("linux_monitor.collectors.memory.psutil.virtual_memory", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    client = make_client()
    response = client.get("/api/v1/system", headers={"Authorization": "Bearer " + "r" * 40})
    data = response.json()
    assert data["memory"]["status"] == "error"
    assert data["memory"]["total_bytes"] is None


def test_filesystem_failure_degrades(monkeypatch):
    monkeypatch.setattr("linux_monitor.collectors.storage.psutil.disk_partitions", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    client = make_client()
    response = client.get("/api/v1/system", headers={"Authorization": "Bearer " + "r" * 40})
    data = response.json()
    assert data["filesystems"] == []
    assert data["filesystems_status"]["status"] == "error"
    assert data["filesystems_status"]["error"] == "collection failed"


def test_network_failure_degrades(monkeypatch):
    monkeypatch.setattr("linux_monitor.collectors.network.psutil.net_io_counters", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    client = make_client()
    response = client.get("/api/v1/system", headers={"Authorization": "Bearer " + "r" * 40})
    data = response.json()
    assert data["network"] == []
    assert data["network_status"]["status"] == "error"


def test_gpu_failure_degrades(monkeypatch):
    monkeypatch.setattr("linux_monitor.collectors.gpu.subprocess.run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr("linux_monitor.collectors.gpu.glob.glob", lambda pattern: (_ for _ in ()).throw(RuntimeError("x")))
    client = make_client()
    response = client.get("/api/v1/system", headers={"Authorization": "Bearer " + "r" * 40})
    data = response.json()
    assert data["gpus"] == []
    assert data["gpu_status"]["status"] == "error"


def test_error_envelope_has_request_id():
    client = make_client()
    response = client.get("/api/v1/system", headers={"Authorization": "Bearer nope"})
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "unauthorized"
    assert "request_id" in body["error"]
    assert response.headers.get("X-Request-ID") == body["error"]["request_id"]
