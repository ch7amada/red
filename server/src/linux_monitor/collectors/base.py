"""Basic system collectors."""

from __future__ import annotations

import platform
import socket
import time
from typing import Optional

import psutil

from ..schemas import OsInfo


def collect_hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def collect_os() -> OsInfo:
    name = platform.system() or "unknown"
    version: Optional[str] = None
    try:
        release_info = platform.freedesktop_os_release()
        name = release_info.get("PRETTY_NAME") or release_info.get("NAME") or name
        version = release_info.get("VERSION_ID") or release_info.get("VERSION")
    except (OSError, AttributeError):
        version = platform.version() or None
    kernel = platform.release() or "unknown"
    architecture = platform.machine() or "unknown"
    if version is None:
        version = platform.version() or None
    return OsInfo(name=name, version=version, kernel=kernel, architecture=architecture)


def collect_uptime() -> Optional[float]:
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        try:
            return max(0.0, time.time() - psutil.boot_time())
        except (OSError, RuntimeError, ValueError):
            return None
