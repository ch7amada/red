import subprocess

from linux_monitor.collectors.gpu import collect_amd, collect_gpus, collect_nvidia
from linux_monitor.config import Settings


def test_absent_gpu(monkeypatch):
    monkeypatch.setattr("linux_monitor.collectors.gpu.subprocess.run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr("linux_monitor.collectors.gpu.glob.glob", lambda pattern: [])
    settings = Settings(environment="test")
    devices, error = collect_gpus(settings)
    assert devices == []
    assert error is None


def test_nvidia_not_executed_with_shell(monkeypatch):
    recorded = {}

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, *a, **k):
        recorded["args"] = args
        recorded["shell"] = k.get("shell", False)
        recorded["timeout"] = k.get("timeout")
        return Result()

    monkeypatch.setattr("linux_monitor.collectors.gpu.subprocess.run", fake_run)
    monkeypatch.setattr("linux_monitor.collectors.gpu.glob.glob", lambda pattern: [])
    collect_nvidia(2.5)
    assert recorded["args"][0] == "/usr/bin/nvidia-smi"
    assert isinstance(recorded["args"], list)
    assert recorded["shell"] is False
    assert recorded["timeout"] == 2.5


def test_multi_nvidia(monkeypatch):
    class Result:
        returncode = 0
        stdout = (
            '0, "GPU A", 10, 100, 200, 30\n'
            '1, "GPU B", 20, 50, 100, 40\n'
        )
        stderr = ""

    monkeypatch.setattr("linux_monitor.collectors.gpu.subprocess.run", lambda *a, **k: Result())
    monkeypatch.setattr("linux_monitor.collectors.gpu.glob.glob", lambda pattern: [])
    settings = Settings(environment="test")
    devices, error = collect_gpus(settings)
    assert error is None
    assert len(devices) == 2
    assert devices[0].id == "nvidia:0"
    assert devices[0].name == "GPU A"
    assert devices[0].vendor == "nvidia"
    assert devices[0].utilization_pct == 10.0
    assert devices[0].vram_used_bytes == 100 * 1024 * 1024
    assert devices[0].vram_total_bytes == 200 * 1024 * 1024
    assert abs(devices[0].vram_used_percent - 50.0) < 1e-9
    assert devices[0].temperature_celsius == 30.0
    assert devices[1].id == "nvidia:1"


def test_nvidia_partial_values(monkeypatch):
    class Result:
        returncode = 0
        stdout = "0, GPU A, N/A, N/A, N/A, N/A\n"
        stderr = ""

    monkeypatch.setattr("linux_monitor.collectors.gpu.subprocess.run", lambda *a, **k: Result())
    monkeypatch.setattr("linux_monitor.collectors.gpu.glob.glob", lambda pattern: [])
    settings = Settings(environment="test")
    devices, error = collect_gpus(settings)
    assert len(devices) == 1
    dev = devices[0]
    assert dev.utilization_pct is None
    assert dev.vram_used_bytes is None
    assert dev.vram_total_bytes is None
    assert dev.vram_used_percent is None
    assert dev.temperature_celsius is None


def test_amd_partial(monkeypatch):
    paths = {
        "/sys/class/drm/card0/device/vendor": "0x1002",
        "/sys/class/drm/card0/device/gpu_busy_percent": "50",
        "/sys/class/drm/card0/device/mem_info_vram_used": "100",
        "/sys/class/drm/card0/device/mem_info_vram_total": "200",
    }

    def fake_read(path):
        return paths.get(path)

    def fake_glob(pattern):
        if pattern == "/sys/class/drm/card[0-9]*":
            return ["/sys/class/drm/card0"]
        if "hwmon" in pattern:
            return []
        return []

    monkeypatch.setattr("linux_monitor.collectors.gpu._read_text", fake_read)
    monkeypatch.setattr("linux_monitor.collectors.gpu.glob.glob", fake_glob)
    monkeypatch.setattr("linux_monitor.collectors.gpu.subprocess.run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))

    devices = collect_amd()
    assert len(devices) == 1
    dev = devices[0]
    assert dev.id == "card0"
    assert dev.vendor == "amd"
    assert dev.name == "AMD GPU"
    assert dev.utilization_pct == 50.0
    assert dev.vram_used_bytes == 100
    assert dev.vram_total_bytes == 200
    assert abs(dev.vram_used_percent - 50.0) < 1e-9
    assert dev.temperature_celsius is None


def test_amd_temperature(monkeypatch):
    paths = {
        "/sys/class/drm/card0/device/vendor": "0x1002",
        "/sys/class/drm/card0/device/gpu_busy_percent": "10",
        "/sys/class/drm/card0/device/mem_info_vram_used": "10",
        "/sys/class/drm/card0/device/mem_info_vram_total": "20",
        "/sys/class/drm/card0/device/hwmon/hwmon0/name": "amdgpu",
        "/sys/class/drm/card0/device/hwmon/hwmon0/temp1_input": "45000",
    }

    def fake_read(path):
        return paths.get(path)

    def fake_glob(pattern):
        if pattern == "/sys/class/drm/card[0-9]*":
            return ["/sys/class/drm/card0"]
        if "hwmon" in pattern:
            return ["/sys/class/drm/card0/device/hwmon/hwmon0"]
        return []

    monkeypatch.setattr("linux_monitor.collectors.gpu._read_text", fake_read)
    monkeypatch.setattr("linux_monitor.collectors.gpu.glob.glob", fake_glob)
    devices = collect_amd()
    assert len(devices) == 1
    assert devices[0].temperature_celsius == 45.0


def test_multi_gpu_mixed(monkeypatch):
    class Result:
        returncode = 0
        stdout = "0, NVIDIA GPU, 30, 64, 128, 50\n"
        stderr = ""

    paths = {
        "/sys/class/drm/card1/device/vendor": "0x1002",
        "/sys/class/drm/card1/device/product_name": "Radeon Test",
    }

    def fake_read(path):
        return paths.get(path)

    def fake_glob(pattern):
        if pattern == "/sys/class/drm/card[0-9]*":
            return ["/sys/class/drm/card1"]
        if "hwmon" in pattern:
            return []
        return []

    monkeypatch.setattr("linux_monitor.collectors.gpu.subprocess.run", lambda *a, **k: Result())
    monkeypatch.setattr("linux_monitor.collectors.gpu._read_text", fake_read)
    monkeypatch.setattr("linux_monitor.collectors.gpu.glob.glob", fake_glob)

    settings = Settings(environment="test")
    devices, error = collect_gpus(settings)
    assert len(devices) == 2
    assert {d.vendor for d in devices} == {"nvidia", "amd"}
    amd = [d for d in devices if d.vendor == "amd"][0]
    assert amd.name == "Radeon Test"


def test_gpu_collector_failure_sets_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("unexpected")

    # Make collect_nvidia raise unexpectedly by patching collect_nvidia? Instead patch subprocess.run to raise RuntimeError
    monkeypatch.setattr("linux_monitor.collectors.gpu.subprocess.run", boom)
    monkeypatch.setattr("linux_monitor.collectors.gpu.glob.glob", lambda pattern: (_ for _ in ()).throw(RuntimeError("boom")))
    settings = Settings(environment="test")
    devices, error = collect_gpus(settings)
    assert devices == []
    assert error == "collection failed"
