from linux_monitor.collectors.cpu import collect_cpu, cpu_percent_from_proc_stat
from linux_monitor.config import Settings


def test_invalid_delta_zero_returns_none():
    prev = "cpu  100 0 0 100 0 0 0 0 0 0\n"
    curr = "cpu  100 0 0 100 0 0 0 0 0 0\n"
    assert cpu_percent_from_proc_stat(prev, curr) is None


def test_negative_delta_returns_none():
    prev = "cpu  100 0 0 100 0 0 0 0 0 0\n"
    curr = "cpu  50 0 0 100 0 0 0 0 0 0\n"
    assert cpu_percent_from_proc_stat(prev, curr) is None


def test_total_delta_zero_returns_none():
    assert cpu_percent_from_proc_stat(None, "cpu 1 2 3 4\n") is None
    assert cpu_percent_from_proc_stat("cpu 1 2 3 4\n", None) is None


def test_valid_delta():
    prev = "cpu  100 0 0 100 0 0 0 0 0 0\n"
    curr = "cpu  110 0 0 105 0 0 0 0 0 0\n"
    value = cpu_percent_from_proc_stat(prev, curr)
    assert value is not None
    # total delta 15, idle delta 5 => 66.67%
    assert abs(value - 66.66666666666667) < 1e-9


def test_collect_cpu_first_sample(monkeypatch):
    calls = {}

    def fake_cpu_percent(interval=None):
        calls["interval"] = interval
        return 42.5

    def fake_loadavg():
        return (1.0, 2.0, 3.0)

    monkeypatch.setattr("linux_monitor.collectors.cpu.psutil.cpu_percent", fake_cpu_percent)
    monkeypatch.setattr("linux_monitor.collectors.cpu.psutil.getloadavg", fake_loadavg)

    settings = Settings(environment="test", cpu_sample_seconds=0.2)
    info = collect_cpu(settings)
    assert info.status == "ok"
    assert info.utilization_pct == 42.5
    assert calls["interval"] == 0.2
    assert info.load_1m == 1.0
    assert info.load_5m == 2.0
    assert info.load_15m == 3.0


def test_collect_cpu_failure(monkeypatch):
    def boom(interval=None):
        raise RuntimeError("cpu boom")

    monkeypatch.setattr("linux_monitor.collectors.cpu.psutil.cpu_percent", boom)
    settings = Settings(environment="test")
    info = collect_cpu(settings)
    assert info.status == "error"
    assert info.utilization_pct is None
    assert info.error == "collection failed"
