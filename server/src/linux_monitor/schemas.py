"""Typed monitoring schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class LlamaCppModel(BaseModel):
    id: str
    status: str
    context_tokens: Optional[int] = None
    training_context_tokens: Optional[int] = None
    total_slots: Optional[int] = None

class LlamaCppInfo(BaseModel):
    status: Literal["running", "loading", "unavailable"]
    error: Optional[str] = None
    models: list[LlamaCppModel] = Field(default_factory=list)


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


class DockerContainerInfo(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    image: str = Field(min_length=1)
    status: str = Field(min_length=1)


class SystemInfo(BaseModel):
    schema_version: str = "1.0"
    llama_cpp: Optional[LlamaCppInfo] = None
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
    docker_containers: list[DockerContainerInfo] = Field(default_factory=list)
    docker_status: ComponentStatus = Field(default_factory=ComponentStatus)

class JobResponse(BaseModel):
    id: str
    kind: str
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    result: Optional[dict[str, Any]] = None
    output: Optional[str] = None
    output_truncated: bool = False
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    poll_url: str


class PowerActionCreateRequest(BaseModel):
    action: Literal["reboot", "shutdown"]
    delay_seconds: int = Field(default=60, ge=10, le=3600)
    confirmation: str

    @model_validator(mode="after")
    def _confirmation_matches_action(self) -> "PowerActionCreateRequest":
        if self.confirmation != self.action:
            raise ValueError("confirmation must exactly equal action")
        return self


class PowerActionResponse(BaseModel):
    id: str
    action: str
    status: str
    created_at: datetime
    scheduled_for: Optional[datetime] = None
    cancellable: bool = False
