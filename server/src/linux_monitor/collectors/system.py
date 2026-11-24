"""System collection orchestration."""

from __future__ import annotations

from datetime import datetime, timezone

from ..config import Settings
from ..schemas import (
    ComponentStatus,
    CpuInfo,
    MemoryInfo,
    OsInfo,
    SwapInfo,
    SystemInfo,
)
from .base import collect_hostname, collect_os, collect_uptime
from .cpu import collect_cpu
from .gpu import collect_gpus
from .memory import collect_memory, collect_swap
from .network import collect_network
from .storage import collect_filesystems


def collect_system(settings: Settings) -> SystemInfo:
    try:
        hostname = collect_hostname()
    except Exception:
        hostname = "unknown"
    try:
        os_info = collect_os()
    except Exception:
        os_info = OsInfo(name="unknown", version=None, kernel="unknown", architecture="unknown")
    try:
        uptime = collect_uptime()
        uptime_status = ComponentStatus(status="ok") if uptime is not None else ComponentStatus(status="error", error="collection failed")
    except Exception:
        uptime = None
        uptime_status = ComponentStatus(status="error", error="collection failed")

    cpu = collect_cpu(settings)
    memory = collect_memory()
    swap = collect_swap()

    try:
        filesystems = collect_filesystems()
        filesystems_status = ComponentStatus(status="ok")
    except Exception:
        filesystems = []
        filesystems_status = ComponentStatus(status="error", error="collection failed")

    try:
        network = collect_network()
        network_status = ComponentStatus(status="ok")
    except Exception:
        network = []
        network_status = ComponentStatus(status="error", error="collection failed")

    try:
        gpus, gpu_error = collect_gpus(settings)
        gpu_status = ComponentStatus(status="error", error=gpu_error) if gpu_error else ComponentStatus(status="ok")
    except Exception:
        gpus = []
        gpu_status = ComponentStatus(status="error", error="collection failed")

    return SystemInfo(
        collected_at=datetime.now(timezone.utc),
        hostname=hostname,
        os=os_info,
        uptime_seconds=uptime,
        uptime_status=uptime_status,
        cpu=cpu,
        memory=memory,
        swap=swap,
        filesystems=filesystems,
        filesystems_status=filesystems_status,
        network=network,
        network_status=network_status,
        gpus=gpus,
        gpu_status=gpu_status,
    )
