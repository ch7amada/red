"""Memory and swap collection."""

from __future__ import annotations

import psutil

from ..schemas import MemoryInfo, SwapInfo


def collect_memory() -> MemoryInfo:
    try:
        vm = psutil.virtual_memory()
        total = int(vm.total)
        available = int(vm.available)
        used = total - available
        used_percent = (used / total * 100.0) if total > 0 else None
        return MemoryInfo(
            status="ok",
            total_bytes=total,
            used_bytes=used,
            available_bytes=available,
            used_percent=used_percent,
        )
    except Exception:
        return MemoryInfo(status="error", error="collection failed")


def collect_swap() -> SwapInfo:
    try:
        sm = psutil.swap_memory()
        total = int(sm.total)
        used = int(sm.used)
        free = total - used
        if free < 0:
            free = int(sm.free) if hasattr(sm, "free") else 0
        used_percent = (used / total * 100.0) if total > 0 else None
        return SwapInfo(
            status="ok",
            total_bytes=total,
            used_bytes=used,
            free_bytes=free,
            used_percent=used_percent,
        )
    except Exception:
        return SwapInfo(status="error", error="collection failed")
