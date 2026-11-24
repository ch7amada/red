from fastapi.testclient import TestClient

from linux_monitor.config import Settings
from linux_monitor.main import create_app


def make_client():
    settings = Settings(reader_token="r" * 40, admin_token="a" * 40, environment="test", cpu_sample_seconds=0.01)
    return TestClient(create_app(settings))


def test_system_schema_and_memory_arithmetic():
    client = make_client()
    response = client.get("/api/v1/system", headers={"Authorization": "Bearer " + "r" * 40})
    assert response.status_code == 200
    data = response.json()

    assert data["schema_version"] == "1.0"
    assert "collected_at" in data
    assert data["hostname"]
    assert data["uptime_seconds"] is None or isinstance(data["uptime_seconds"], (int, float))
    assert data["os"]["name"]
    assert data["os"]["kernel"]
    assert data["os"]["architecture"]

    cpu = data["cpu"]
    assert cpu["status"] == "ok"
    assert isinstance(cpu["utilization_pct"], (int, float))
    assert 0 <= cpu["utilization_pct"] <= 100
    for key in ("load_1m", "load_5m", "load_15m"):
        assert isinstance(cpu[key], (int, float))

    memory = data["memory"]
    assert memory["status"] == "ok"
    assert memory["used_bytes"] == memory["total_bytes"] - memory["available_bytes"]
    assert 0 <= memory["used_percent"] <= 100

    assert isinstance(data["filesystems"], list)
    assert isinstance(data["network"], list)
    assert isinstance(data["gpus"], list)

    # collected_at is UTC RFC3339
    assert "T" in data["collected_at"]


def test_collected_at_utc():
    client = make_client()
    response = client.get("/api/v1/system", headers={"Authorization": "Bearer " + "r" * 40})
    data = response.json()
    # Accept +00:00 or Z
    assert data["collected_at"].endswith("+00:00") or data["collected_at"].endswith("Z")
