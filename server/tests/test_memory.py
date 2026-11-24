from linux_monitor.collectors.memory import collect_memory, collect_swap
from linux_monitor.config import Settings


class FakeVM:
    total = 1000
    available = 300


class FakeSwap:
    total = 500
    used = 200
    free = 300


def test_memory_arithmetic(monkeypatch):
    monkeypatch.setattr("linux_monitor.collectors.memory.psutil.virtual_memory", lambda: FakeVM())
    info = collect_memory()
    assert info.status == "ok"
    assert info.total_bytes == 1000
    assert info.available_bytes == 300
    assert info.used_bytes == 700
    assert abs(info.used_percent - 70.0) < 1e-9


def test_swap(monkeypatch):
    monkeypatch.setattr("linux_monitor.collectors.memory.psutil.swap_memory", lambda: FakeSwap())
    info = collect_swap()
    assert info.status == "ok"
    assert info.total_bytes == 500
    assert info.used_bytes == 200
    assert info.free_bytes == 300
    assert abs(info.used_percent - 40.0) < 1e-9


def test_memory_failure(monkeypatch):
    def boom():
        raise RuntimeError("mem boom")

    monkeypatch.setattr("linux_monitor.collectors.memory.psutil.virtual_memory", boom)
    info = collect_memory()
    assert info.status == "error"
    assert info.total_bytes is None
    assert info.used_bytes is None
    assert info.available_bytes is None
    assert info.used_percent is None
