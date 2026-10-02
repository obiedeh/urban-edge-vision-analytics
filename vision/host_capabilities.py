"""Detect what this host can run: platform, RAM, VRAM, container runtime.

Used for the model-catalog preflight (hide or flag models that will not fit)
and for the environment default (Jetson → Cosmos-Reason2-2B via vLLM,
x86 + large discrete GPU → Gemma 4).
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class HostCapabilities:
    hostname: str
    machine: str
    is_jetson: bool
    jetson_model: str | None
    gpu_name: str | None
    gpu_vram_total_gb: float | None
    gpu_vram_free_gb: float | None
    ram_total_gb: float | None
    ram_available_gb: float | None
    unified_memory: bool
    has_docker: bool
    has_vllm_binary: bool
    has_ollama: bool
    recommended_profile: str  # "jetson-thor" | "workstation-gpu" | "cpu"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def budget_gb(self) -> float | None:
        """Memory a model can use: VRAM on discrete GPUs, available RAM on unified."""
        if self.unified_memory:
            return self.ram_available_gb
        return self.gpu_vram_free_gb if self.gpu_vram_free_gb is not None else self.ram_available_gb


def _meminfo() -> tuple[float | None, float | None]:
    total = avail = None
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    total = float(line.split()[1]) / (1024 * 1024)
                elif line.startswith("MemAvailable:"):
                    avail = float(line.split()[1]) / (1024 * 1024)
    except OSError:
        pass
    return total, avail


def _jetson_model() -> str | None:
    for path in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        try:
            text = Path(path).read_text(errors="ignore").strip("\x00\n ")
            if text:
                return text
        except OSError:
            continue
    if Path("/etc/nv_tegra_release").exists():
        return "NVIDIA Jetson"
    return None


def _nvidia_smi() -> tuple[str | None, float | None, float | None]:
    if shutil.which("nvidia-smi") is None:
        return None, None, None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, check=True,
        ).stdout.strip().splitlines()
    except (subprocess.SubprocessError, OSError):
        return None, None, None
    if not out:
        return None, None, None
    parts = [p.strip() for p in out[0].split(",")]
    name = parts[0] if parts else None

    def num(v: str) -> float | None:
        try:
            return float(v) / 1024
        except ValueError:
            return None  # Jetson reports "[N/A]"

    total = num(parts[1]) if len(parts) > 1 else None
    free = num(parts[2]) if len(parts) > 2 else None
    return name, total, free


def detect_host() -> HostCapabilities:
    machine = platform.machine()
    jetson = _jetson_model()
    is_jetson = jetson is not None
    gpu_name, vram_total, vram_free = _nvidia_smi()
    ram_total, ram_avail = _meminfo()
    unified = is_jetson or (vram_total is None and gpu_name is not None)
    if is_jetson and not gpu_name:
        gpu_name = jetson
    has_docker = shutil.which("docker") is not None
    has_vllm = bool(os.getenv("VLLM_BIN")) or shutil.which("vllm") is not None
    has_ollama = shutil.which("ollama") is not None
    if is_jetson:
        big = "thor" in (jetson or "").lower() or (ram_total or 0) > 64
        profile = "jetson-thor" if big else "jetson"
    elif gpu_name:
        profile = "workstation-gpu"
    else:
        profile = "cpu"
    return HostCapabilities(
        hostname=platform.node(),
        machine=machine,
        is_jetson=is_jetson,
        jetson_model=jetson,
        gpu_name=gpu_name,
        gpu_vram_total_gb=round(vram_total, 1) if vram_total else None,
        gpu_vram_free_gb=round(vram_free, 1) if vram_free else None,
        ram_total_gb=round(ram_total, 1) if ram_total else None,
        ram_available_gb=round(ram_avail, 1) if ram_avail else None,
        unified_memory=unified,
        has_docker=has_docker,
        has_vllm_binary=has_vllm,
        has_ollama=has_ollama,
        recommended_profile=profile,
    )


def default_model_for(caps: HostCapabilities) -> dict[str, Any]:
    """Environment-based default model selection (editable afterwards in the UI)."""
    if caps.is_jetson:
        return {
            "backend": "vllm",
            "endpoint": "http://localhost:8000",
            "model": "nvidia/cosmos-reason2-2b",
            "label": "Cosmos Reason 2 (2B) — vLLM (Jetson default)",
            "think": False,
            "max_tokens": 512,
        }
    if caps.gpu_name and caps.has_ollama:
        return {
            "backend": "ollama",
            "endpoint": "http://localhost:11434",
            "model": "gemma4:e4b",
            "label": "Gemma 4 E4B — Ollama (workstation default)",
            "think": False,
            "max_tokens": 512,
        }
    if caps.gpu_name:
        return {
            "backend": "vllm",
            "endpoint": "http://localhost:8000",
            "model": "google/gemma-4-E4B-it",
            "label": "Gemma 4 E4B — vLLM (workstation default)",
            "think": False,
            "max_tokens": 512,
        }
    return {"backend": "mock", "endpoint": "", "model": "", "label": "Mock detector (no GPU found)"}
