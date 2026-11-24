"""Network collection."""

from __future__ import annotations

import psutil

from ..schemas import NetworkInterfaceInfo


def collect_network() -> list[NetworkInterfaceInfo]:
    result: list[NetworkInterfaceInfo] = []
    counters = psutil.net_io_counters(pernic=True) or {}
    for name in sorted(counters):
        c = counters[name]
        result.append(
            NetworkInterfaceInfo(
                name=name,
                rx_bytes=int(c.bytes_recv),
                tx_bytes=int(c.bytes_sent),
                rx_packets=int(c.packets_recv),
                tx_packets=int(c.packets_sent),
                rx_errors=int(c.errin),
                tx_errors=int(c.errout),
                rx_dropped=int(c.dropin),
                tx_dropped=int(c.dropout),
            )
        )
    return result
