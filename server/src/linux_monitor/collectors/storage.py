"""Filesystem collection."""

from __future__ import annotations

import psutil

from ..schemas import FileSystemInfo


def collect_filesystems() -> list[FileSystemInfo]:
    result: list[FileSystemInfo] = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (OSError, RuntimeError, PermissionError, ValueError):
            continue
        total = int(usage.total)
        used = int(usage.used)
        available = int(usage.free)
        used_percent = (used / total * 100.0) if total > 0 else None
        result.append(
            FileSystemInfo(
                device=part.device,
                mountpoint=part.mountpoint,
                fstype=part.fstype,
                total_bytes=total,
                used_bytes=used,
                available_bytes=available,
                used_percent=used_percent,
            )
        )
    return result
