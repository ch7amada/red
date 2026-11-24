"""Typed monitoring schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class OsInfo(BaseModel):
    name: str
    version: Optional[str] = None
    kernel: str
    architecture: str


class ComponentStatus(BaseModel):
    status: Literal["ok", "error"] = "ok"
    error: Optional[str] = None


class CpuInfo(BaseModel):
    status: Literal["ok", "error"] = "ok"
    error: Optional[str] = None
    utilization_pct: Optional[float] = None
    load_1m: Optional[float] = None
    load_5m: Optional[float] = None
    load_15m: Optional[float] = None


class MemoryInfo(BaseModel):
    status: Literal["ok", "error"] = "ok"
    error: Optional[str] = None
    total_bytes: Optional[int] = None
    used_bytes: Optional[int] = None
    available_bytes: Optional[int] = None
    used_percent: Optional[float] = None


class SwapInfo(BaseModel):
    status: Literal["ok", "error"] = "ok"
    error: Optional[str] = None
    total_bytes: Optional[int] = None
    used_bytes: Optional[int] = None
    free_bytes: Optional[int] = None
    used_percent: Optional[float] = None


class FileSystemInfo(BaseModel):
    device: Optional[str] = None
    mountpoint: str
    fstype: Optional[str] = None
    total_bytes: Optional[int] = None
    used_bytes: Optional[int] = None
    available_bytes: Optional[int] = None
    used_percent: Optional[float] = None


class NetworkInterfaceInfo(BaseModel):
    name: str
    rx_bytes: Optional[int] = None
    tx_bytes: Optional[int] = None
    rx_packets: Optional[int] = None
    tx_packets: Optional[int] = None
    rx_errors: Optional[int] = None
    tx_errors: Optional[int] = None
    rx_dropped: Optional[int] = None
    tx_dropped: Optional[int] = None


class GpuInfo(BaseModel):
    id: str
    name: str
    vendor: Literal["nvidia", "amd", "unknown"] = "unknown"
    status: Literal["ok", "error"] = "ok"
    error: Optional[str] = None
    utilization_pct: Optional[float] = None
    vram_used_bytes: Optional[int] = None
    vram_total_bytes: Optional[int] = None
    vram_used_percent: Optional[float] = None
    temperature_celsius: Optional[float] = None


class SystemInfo(BaseModel):
    schema_version: str = "1.0"
    collected_at: datetime
    hostname: str
    os: OsInfo
    uptime_seconds: Optional[float] = None
    uptime_status: ComponentStatus = Field(default_factory=ComponentStatus)
    cpu: CpuInfo
    memory: MemoryInfo
    swap: SwapInfo
    filesystems: list[FileSystemInfo] = Field(default_factory=list)
    filesystems_status: ComponentStatus = Field(default_factory=ComponentStatus)
    network: list[NetworkInterfaceInfo] = Field(default_factory=list)
    network_status: ComponentStatus = Field(default_factory=ComponentStatus)
    gpus: list[GpuInfo] = Field(default_factory=list)
    gpu_status: ComponentStatus = Field(default_factory=ComponentStatus)