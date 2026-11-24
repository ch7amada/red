"""GPU collection."""

from __future__ import annotations

import csv
import glob
import io
import os
import re
import subprocess
from typing import Optional

from ..config import Settings
from ..schemas import GpuInfo

NVIDIA_SMI = "/usr/bin/nvidia-smi"


def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except (OSError, UnicodeError, ValueError):
        return None


def _parse_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    text = value.strip()
    if not text or text.upper() in {"N/A", "[N/A]", "NA", "NONE"}:
        return None
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


def _parse_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    text = value.strip()
    if not text or text.upper() in {"N/A", "[N/A]", "NA", "NONE"}:
        return None
    try:
        return int(float(text))
    except (ValueError, TypeError):
        return None


def collect_nvidia(timeout: float) -> tuple[list[GpuInfo], Optional[str]]:
    devices: list[GpuInfo] = []
    try:
        result = subprocess.run(
            [
                NVIDIA_SMI,
                "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return devices, None
    except Exception:
        return devices, "collection failed"
    if result.returncode != 0:
        return devices, "collection failed"
    try:
        reader = csv.reader(io.StringIO(result.stdout or ""))
        for row in reader:
            if not row or len(row) < 6:
                continue
            index = row[0].strip().strip(chr(34)).strip(chr(39))
            name = row[1].strip().strip(chr(34)).strip(chr(39)) or "NVIDIA GPU"
            utilization = _parse_float(row[2])
            mem_used_raw = _parse_float(row[3])
            mem_total_raw = _parse_float(row[4])
            temperature = _parse_float(row[5])
            mem_used_bytes = int(mem_used_raw * 1024 * 1024) if mem_used_raw is not None else None
            mem_total_bytes = int(mem_total_raw * 1024 * 1024) if mem_total_raw is not None else None
            vram_percent = None
            if mem_used_bytes is not None and mem_total_bytes and mem_total_bytes > 0:
                vram_percent = mem_used_bytes / mem_total_bytes * 100.0
            device_id = f"nvidia:{index}" if index else f"nvidia:{len(devices)}"
            devices.append(
                GpuInfo(
                    id=device_id,
                    name=name,
                    vendor="nvidia",
                    utilization_pct=utilization,
                    vram_used_bytes=mem_used_bytes,
                    vram_total_bytes=mem_total_bytes,
                    vram_used_percent=vram_percent,
                    temperature_celsius=temperature,
                )
            )
    except Exception:
        return devices, "collection failed"
    return devices, None


def collect_amd() -> list[GpuInfo]:
    devices: list[GpuInfo] = []
    for card_path in sorted(glob.glob("/sys/class/drm/card[0-9]*")):
        basename = os.path.basename(card_path)
        if not re.fullmatch(r"card\d+", basename):
            continue
        vendor = _read_text(os.path.join(card_path, "device", "vendor"))
        if vendor != "0x1002":
            continue
        name = (
            _read_text(os.path.join(card_path, "device", "product_name"))
            or _read_text(os.path.join(card_path, "device", "name"))
            or "AMD GPU"
        )
        utilization = _parse_float(_read_text(os.path.join(card_path, "device", "gpu_busy_percent")))
        vram_used = _parse_int(_read_text(os.path.join(card_path, "device", "mem_info_vram_used")))
        vram_total = _parse_int(_read_text(os.path.join(card_path, "device", "mem_info_vram_total")))
        vram_percent = None
        if vram_used is not None and vram_total and vram_total > 0:
            vram_percent = vram_used / vram_total * 100.0
        temperature: Optional[float] = None
        for hwmon in sorted(glob.glob(os.path.join(card_path, "device", "hwmon", "hwmon*"))):
            hw_name = _read_text(os.path.join(hwmon, "name"))
            if hw_name is not None and hw_name != "amdgpu":
                continue
            raw_temp = _read_text(os.path.join(hwmon, "temp1_input"))
            parsed = _parse_float(raw_temp)
            if parsed is not None:
                temperature = parsed / 1000.0
                break
        devices.append(
            GpuInfo(
                id=basename,
                name=name,
                vendor="amd",
                utilization_pct=utilization,
                vram_used_bytes=vram_used,
                vram_total_bytes=vram_total,
                vram_used_percent=vram_percent,
                temperature_celsius=temperature,
            )
        )
    return devices


def collect_gpus(settings: Settings) -> tuple[list[GpuInfo], Optional[str]]:
    devices: list[GpuInfo] = []
    error: Optional[str] = None
    try:
        nvidia_devices, nvidia_error = collect_nvidia(float(settings.gpu_timeout_seconds))
        devices.extend(nvidia_devices)
        if nvidia_error is not None and error is None:
            error = nvidia_error
    except Exception:
        if error is None:
            error = "collection failed"
    try:
        devices.extend(collect_amd())
    except Exception:
        if error is None:
            error = "collection failed"
    return devices, error