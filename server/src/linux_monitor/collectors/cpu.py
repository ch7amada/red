"""CPU collection."""

from __future__ import annotations

from typing import Optional, Tuple

import psutil

from ..config import Settings
from ..schemas import CpuInfo


def cpu_percent_from_proc_stat(prev_text: Optional[str], curr_text: Optional[str]) -> Optional[float]:
    """Compute CPU utilization from two /proc/stat snapshots."""
    if not prev_text or not curr_text:
        return None
    try:
        prev_line = next((line for line in prev_text.splitlines() if line.startswith("cpu ")), "")
        curr_line = next((line for line in curr_text.splitlines() if line.startswith("cpu ")), "")
        if not prev_line or not curr_line:
            return None
        prev_vals = [int(value) for value in prev_line.split()[1:]]
        curr_vals = [int(value) for value in curr_line.split()[1:]]
        if len(prev_vals) < 4 or len(curr_vals) < len(prev_vals):
            return None
        deltas = [curr - prev for prev, curr in zip(prev_vals, curr_vals)]
        if any(delta < 0 for delta in deltas):
            return None
        idle_delta = deltas[3] + (deltas[4] if len(deltas) > 4 else 0)
        total_delta = sum(deltas)
        if total_delta <= 0:
            return None
        utilization = ((total_delta - idle_delta) / total_delta) * 100.0
        if utilization < 0 or utilization > 100:
            return None
        return utilization
    except (ValueError, IndexError, TypeError, AttributeError):
        return None


def collect_cpu(settings: Settings) -> CpuInfo:
    try:
        interval = max(0.01, float(settings.cpu_sample_seconds))
        utilization = psutil.cpu_percent(interval=interval)
        try:
            load1, load5, load15 = psutil.getloadavg()
        except (AttributeError, OSError):
            load1, load5, load15 = _read_loadavg()
        return CpuInfo(
            status="ok",
            utilization_pct=float(utilization),
            load_1m=None if load1 is None else float(load1),
            load_5m=None if load5 is None else float(load5),
            load_15m=None if load15 is None else float(load15),
        )
    except Exception:
        return CpuInfo(status="error", error="collection failed")


def _read_loadavg() -> Tuple[Optional[float], Optional[float], Optional[float]]:
    try:
        with open("/proc/loadavg", "r", encoding="utf-8") as f:
            parts = f.read().split()[:3]
        return float(parts[0]), float(parts[1]), float(parts[2])
    except (OSError, ValueError, IndexError):
        return None, None, None



