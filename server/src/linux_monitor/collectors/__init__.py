"""Monitoring collectors."""

from .cpu import (
    collect_cpu,
    cpu_percent_from_proc_stat,
)
from .gpu import collect_gpus
from .memory import collect_memory, collect_swap
from .network import collect_network
from .storage import collect_filesystems
from .system import collect_system
from .base import (
    collect_hostname,
    collect_os,
    collect_uptime,
)

__all__ = [
    "collect_cpu",
    "cpu_percent_from_proc_stat",
    "collect_gpus",
    "collect_memory",
    "collect_swap",
    "collect_network",
    "collect_filesystems",
    "collect_system",
    "collect_hostname",
    "collect_os",
    "collect_uptime",
]
