import pytest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from linux_monitor.config import Settings
from linux_monitor.collectors.docker import collect_docker
from linux_monitor.main import create_app


def make_settings():
    return Settings(reader_token="r" * 40, admin_token="a" * 40, environment="test", cpu_sample_seconds=0.01)


@pytest.mark.parametrize(
    "stdout,rc,timed_out,truncated,err,expected_count",
    [
        ('{"containers":[{"id":"abc","name":"web","image":"nginx","status":"Up"}]}', 0, False, False, None, 1),
        ('{"containers":[]}', 0, False, False, None, 0),
        ("", 1, False, False, "collection failed", 0),
        ("", 0, True, False, "collection failed", 0),
        ('{"containers":[]}', 0, False, True, "collection failed", 0),
        ("not json", 0, False, False, "collection failed", 0),
        ('{"foo":[]}', 0, False, False, "collection failed", 0),
        ('{"containers":[{"id":"x"}]}', 0, False, False, "collection failed", 0),
        ('{"containers":[{"id":"","name":"x","image":"y","status":"z"}]}', 0, False, False, "collection failed", 0),
        ('{"containers":"nope"}', 0, False, False, "collection failed", 0),
    ],
)
def test_collect_docker(monkeypatch, stdout, rc, timed_out, truncated, err, expected_count):
    def fake_run(argv, *, timeout=None, env=None, cwd=None):
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr="", timed_out=timed_out, stdout_truncated=truncated)

    monkeypatch.setattr("linux_monitor.collectors.docker.run_process", fake_run)
    containers, error = collect_docker(make_settings())
    assert error == err
    if err is None:
        assert len(containers) == expected_count
        if expected_count:
            assert containers[0].id == "abc"
    else:
        assert containers == []


@pytest.mark.parametrize(
    "stdout,rc,expected_status,expected_count",
    [
        ('{"containers":[{"id":"abc","name":"web","image":"nginx","status":"Up"}]}', 0, "ok", 1),
        ("", 1, "error", 0),
        ('{"containers":[{"id":"x"}]}', 0, "error", 0),
    ],
)
def test_docker_snapshot(monkeypatch, stdout, rc, expected_status, expected_count):
    def fake_run(argv, *, timeout=None, env=None, cwd=None):
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr="", timed_out=False, stdout_truncated=False)

    monkeypatch.setattr("linux_monitor.collectors.docker.run_process", fake_run)
    settings = make_settings()
    client = TestClient(create_app(settings))
    resp = client.get("/api/v1/system", headers={"Authorization": "Bearer " + "r" * 40})
    assert resp.status_code == 200
    data = resp.json()
    assert data["docker_status"]["status"] == expected_status
    assert len(data["docker_containers"]) == expected_count
    assert data["cpu"]["status"] == "ok"
    assert data["memory"]["status"] == "ok"