"""Routes for querying locally-running inference servers (Ollama, vLLM).

These endpoints are called by the UI adapter switcher to:
  - Check if a local server is reachable
  - List available models
  - Identify which models are vision-capable
  - Return a curated model catalog with hardware requirements

No credentials are required for local servers.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.vllm_manager import DockerLaunch, VllmServerManager, parse_local_vllm_endpoint
from store.config_store import ConfigStore
from store.models import ModelSettings
from vision.host_capabilities import HostCapabilities, detect_host

router = APIRouter(prefix="/inference", tags=["local-inference"])

OLLAMA_BASE = "http://localhost:11434"
VLLM_BASE   = "http://localhost:8000"   # default — user can override via ?endpoint=

# NVIDIA's vLLM container for JetPack 7 / Thor (the only supported vLLM path there).
JETSON_VLLM_IMAGE = os.getenv(
    "URBAN_EDGE_JETSON_VLLM_IMAGE",
    "ghcr.io/nvidia-ai-iot/vllm:0.14.0-r38.3-arm64-sbsa-cu130-24.04",
)
JETSON_MODELS_DIR = os.getenv("URBAN_EDGE_MODELS_DIR", "~/models")


def _get_vllm_manager() -> VllmServerManager:
    """Overridden in api/main.py after the manager is created."""
    raise RuntimeError("VllmServerManager not initialised")  # pragma: no cover


def _get_store() -> ConfigStore:
    raise RuntimeError("Store not initialised")  # pragma: no cover


def _get_runtime() -> Any:
    return None


class VllmStartRequest(BaseModel):
    model: str = Field(min_length=1)
    endpoint: str = VLLM_BASE
    launcher: str = "auto"          # auto | binary | docker
    model_path: str = ""            # docker: host directory holding the weights
    gpu_memory_utilization: float = Field(default=0.25, gt=0.05, le=0.95)
    max_model_len: int = Field(default=8192, ge=1024, le=131072)
    apply: bool = True              # also select this model in the running app


class VllmStopRequest(BaseModel):
    # The server may be shared with another app on the device: stopping it is
    # deliberate, logged with the caller, never implicit.
    confirm: bool = False
    reason: str = ""


logger = logging.getLogger("api.inference")


class ApplyModelRequest(BaseModel):
    backend: str
    model: str
    endpoint: str = ""
    api_key: str = ""
    think: bool = False
    max_tokens: int = 512
    label: str = ""

# Ollama model families that support vision (image input)
_OLLAMA_VISION_FAMILIES = {
    "llava", "moondream", "llava-phi3", "minicpm", "bakllava",
    "llava-llama3", "llama3.2-vision", "granite3", "qwen2-vl",
    "gemma3", "gemma4",                   # Google Gemma 3/4 multimodal
    "cosmos", "cosmos-reason2", "cosmos3", # NVIDIA Cosmos world-model family
    "phi3-vision", "phi4-vision",         # Microsoft Phi vision
    "internvl", "internvl2",              # InternVL series
    "cogvlm", "cogvlm2",
}

# Keywords in model names that indicate vision capability
_VISION_KEYWORDS = {
    "llava", "vision", "moondream", "vl", "visual", "minicpm",
    "cosmos", "cosmos-reason", "cosmos3", # NVIDIA Cosmos
    "gemma3", "gemma4",                   # Gemma multimodal
    "internvl", "cogvlm",
    "phi3v", "phi4v",
}

# ── Curated model catalog ─────────────────────────────────────────────────────
#
# Tier guide
#   "nano"    < 2 GB VRAM / CPU-only OK (e.g. moondream)
#   "mid"     4–8 GB VRAM (RTX 3060 / Jetson Orin)
#   "high"    8–16 GB VRAM (RTX 3090 / Jetson Thor)
#   "max"     16–32 GB VRAM (RTX 4090 / RTX 5090 / Jetson Thor AGX)
#
# "backend" tells the UI which server to use:
#   "ollama"  → pull with `ollama pull <name>`
#   "vllm"    → serve with `vllm serve <hf_id>`

MODEL_CATALOG: list[dict] = [
    # ── NVIDIA Cosmos ─────────────────────────────────────────────────────────
    {
        "name": "nvidia/cosmos-reason2-2b",
        "hf_id": "nvidia/Cosmos-Reason2-2B",
        "label": "Cosmos Reason 2 (2B) via vLLM",
        "family": "cosmos-reason2",
        "vision": True,
        "params_b": 2.0,
        "vram_gb": 5,
        "tier": "mid",
        "backend": "vllm",
        "description": "Gated Hugging Face repo; use after NVIDIA/HF access is granted",
        "pull_cmd": "vllm serve nvidia/Cosmos-Reason2-2B --port 8000",
        "gated": True,
        "access_note": "Requires Hugging Face access to nvidia/Cosmos-Reason2-2B.",
        "served_model_name": "nvidia/cosmos-reason2-2b",
        "jetson_model_dir": "cosmos-reason2-2b",
        "jetson_gpu_memory_utilization": 0.25,
        "tags": ["nvidia", "traffic", "world-model", "gated", "jetson-thor"],
    },
    {
        "name": "nvidia/cosmos-reason2-8b",
        "hf_id": "nvidia/Cosmos-Reason2-8B",
        "label": "Cosmos Reason 2 (8B) via vLLM",
        "family": "cosmos-reason2",
        "vision": True,
        "params_b": 8.0,
        "vram_gb": 18,
        "tier": "max",
        "backend": "vllm",
        "description": "Larger Cosmos Reason 2; measured at ~0.1-0.2 fps on Jetson AGX Thor",
        "pull_cmd": "vllm serve nvidia/Cosmos-Reason2-8B --port 8000",
        "gated": True,
        "served_model_name": "nvidia/cosmos-reason2-8b",
        "jetson_model_dir": "cosmos-reason2-8b",
        "jetson_gpu_memory_utilization": 0.35,
        "tags": ["nvidia", "traffic", "world-model", "gated", "jetson-thor"],
    },
    {
        "name": "nvidia/cosmos3-nano-reasoner",
        "hf_id": "nvidia/Cosmos3-Nano",
        "label": "Cosmos 3 Nano Reasoner (8B)",
        "family": "cosmos3",
        "vision": True,
        "params_b": 8.0,
        "vram_gb": 18,
        "ram_gb": 40,
        "tier": "max",
        "backend": "vllm",
        "description": "Cosmos 3 Nano via vLLM-Omni; needs high system RAM",
        "pull_cmd": (
            "NIM_MODEL_SIZE=nano vllm-omni serve nvidia/Cosmos3-Nano "
            "--omni --model-class-name Cosmos3OmniDiffusersPipeline "
            "--enable-layerwise-offload --vae-use-slicing --vae-use-tiling "
            "--disable-multithread-weight-load "
            "--diffusion-attention-backend TORCH_SDPA --no-guardrails "
            "--log-file /tmp/urban-edge-vllm-cosmos3.log --init-timeout 1800 --port 8000"
        ),
        "launch_bin": "vllm-omni",
        "launch_args": [
            "--omni",
            "--model-class-name",
            "Cosmos3OmniDiffusersPipeline",
            "--enable-layerwise-offload",
            "--vae-use-slicing",
            "--vae-use-tiling",
            "--disable-multithread-weight-load",
            "--diffusion-attention-backend",
            "TORCH_SDPA",
            "--no-guardrails",
            "--log-file",
            "/tmp/urban-edge-vllm-cosmos3.log",
            "--init-timeout",
            "1800",
        ],
        "launch_env": {"NIM_MODEL_SIZE": "nano"},
        "tags": ["nvidia", "traffic", "world-model", "cosmos3"],
    },
    # ── Google Gemma ──────────────────────────────────────────────────────────
    {
        "name": "gemma3:4b-instruct-vision",
        "hf_id": "google/gemma-3-4b-it",
        "label": "Gemma 3 Vision (4B)",
        "family": "gemma3",
        "vision": True,
        "params_b": 4.0,
        "vram_gb": 6,
        "tier": "mid",
        "backend": "ollama",
        "description": "Google Gemma 3 with vision — good balance of speed and accuracy",
        "pull_cmd": "ollama pull gemma3:4b-instruct-vision",
        "tags": ["google", "vision"],
    },
    {
        "name": "gemma3:12b-instruct-vision-q4_K_M",
        "hf_id": "google/gemma-3-12b-it",
        "label": "Gemma 3 Vision (12B Q4)",
        "family": "gemma3",
        "vision": True,
        "params_b": 12.0,
        "vram_gb": 7,
        "tier": "high",
        "backend": "ollama",
        "description": "12B quantized — high quality, fits RTX 3090 / Jetson Thor",
        "pull_cmd": "ollama pull gemma3:12b-instruct-vision-q4_K_M",
        "tags": ["google", "vision", "quantized"],
    },
    {
        "name": "gemma3:27b-instruct-vision-q4_K_M",
        "hf_id": "google/gemma-3-27b-it",
        "label": "Gemma 3 Vision (27B Q4)",
        "family": "gemma3",
        "vision": True,
        "params_b": 27.0,
        "vram_gb": 15,
        "tier": "max",
        "backend": "ollama",
        "description": "27B quantized — best quality, RTX 5090 or Jetson Thor AGX",
        "pull_cmd": "ollama pull gemma3:27b-instruct-vision-q4_K_M",
        "tags": ["google", "vision", "quantized", "high-param"],
    },
    {
        "name": "gemma4:e2b",
        "hf_id": "google/gemma-4-E2B-it",
        "label": "Gemma 4 Edge (E2B)",
        "family": "gemma4",
        "vision": True,
        "params_b": 2.3,
        "vram_gb": 8,
        "tier": "high",
        "backend": "ollama",
        "description": "Smallest Gemma 4 multimodal Ollama tag; safest quantized choice",
        "pull_cmd": "ollama pull gemma4:e2b",
        "tags": ["google", "vision", "quantized", "edge"],
    },
    {
        "name": "gemma4:e4b",
        "hf_id": "google/gemma-4-E4B-it",
        "label": "Gemma 4 Edge (E4B)",
        "family": "gemma4",
        "vision": True,
        "params_b": 4.5,
        "vram_gb": 12,
        "tier": "high",
        "backend": "ollama",
        "description": "Recommended quantized Gemma 4 starting point for live traffic frames",
        "pull_cmd": "ollama pull gemma4:e4b",
        "tags": ["google", "vision", "quantized", "recommended"],
    },
    {
        "name": "google/gemma-4-E4B-it",
        "hf_id": "google/gemma-4-E4B-it",
        "label": "Gemma 4 Edge (E4B) via vLLM",
        "family": "gemma4",
        "vision": True,
        "params_b": 4.5,
        "vram_gb": 14,
        "tier": "high",
        "backend": "vllm",
        "description": "Official Gemma 4 E4B checkpoint; smallest practical vLLM Gemma 4 target",
        "pull_cmd": "vllm serve google/gemma-4-E4B-it --port 8000 --trust-remote-code",
        "launch_args": ["--trust-remote-code"],
        "tags": ["google", "vision", "recommended"],
    },
    {
        "name": "gemma4:12b",
        "hf_id": "google/gemma-4-12B-it",
        "label": "Gemma 4 Unified (12B)",
        "family": "gemma4",
        "vision": True,
        "params_b": 12.0,
        "vram_gb": 14,
        "tier": "high",
        "backend": "ollama",
        "description": "Stronger quantized Gemma 4 option that still fits comfortably on RTX 5090",
        "pull_cmd": "ollama pull gemma4:12b",
        "tags": ["google", "vision", "quantized"],
    },
    {
        "name": "gemma4:26b",
        "hf_id": "google/gemma-4-26B-A4B-it",
        "label": "Gemma 4 MoE (26B A4B)",
        "family": "gemma4",
        "vision": True,
        "params_b": 25.2,
        "vram_gb": 24,
        "tier": "max",
        "backend": "ollama",
        "description": "Large quantized Gemma 4 option; stop other GPU workloads before live use",
        "pull_cmd": "ollama pull gemma4:26b",
        "tags": ["google", "vision", "quantized", "high-param"],
    },
    {
        "name": "gemma4:31b",
        "hf_id": "google/gemma-4-31B-it",
        "label": "Gemma 4 Dense (31B)",
        "family": "gemma4",
        "vision": True,
        "params_b": 30.7,
        "vram_gb": 28,
        "tier": "max",
        "backend": "ollama",
        "description": "Largest quantized Gemma 4 Ollama tag; dedicate most of the GPU to it",
        "pull_cmd": "ollama pull gemma4:31b",
        "tags": ["google", "vision", "quantized", "high-param", "latest"],
    },
    {
        "name": "nvidia/Gemma-4-26B-A4B-NVFP4",
        "hf_id": "nvidia/Gemma-4-26B-A4B-NVFP4",
        "label": "Gemma 4 MoE (26B A4B NVFP4)",
        "family": "gemma4",
        "vision": True,
        "params_b": 25.2,
        "vram_gb": 20,
        "tier": "max",
        "backend": "vllm",
        "description": "NVIDIA-optimized quantized Gemma 4 checkpoint for Blackwell vLLM",
        "pull_cmd": (
            "vllm serve nvidia/Gemma-4-26B-A4B-NVFP4 --trust-remote-code "
            "--tool-call-parser gemma4 --reasoning-parser gemma4 "
            "--enable-auto-tool-choice"
        ),
        "launch_args": [
            "--trust-remote-code",
            "--tool-call-parser",
            "gemma4",
            "--reasoning-parser",
            "gemma4",
            "--enable-auto-tool-choice",
        ],
        "tags": ["google", "nvidia", "vision", "quantized", "nvfp4"],
    },
    # ── LLaVA variants ────────────────────────────────────────────────────────
    {
        "name": "llava:7b",
        "hf_id": "llava-hf/llava-1.5-7b-hf",
        "label": "LLaVA 1.5 (7B)",
        "family": "llava",
        "vision": True,
        "params_b": 7.0,
        "vram_gb": 6,
        "tier": "mid",
        "backend": "ollama",
        "description": "Classic vision LLM, well-tested on scene description",
        "pull_cmd": "ollama pull llava:7b",
        "tags": ["vision", "classic"],
    },
    {
        "name": "llava:13b",
        "hf_id": "llava-hf/llava-1.5-13b-hf",
        "label": "LLaVA 1.5 (13B)",
        "family": "llava",
        "vision": True,
        "params_b": 13.0,
        "vram_gb": 9,
        "tier": "high",
        "backend": "ollama",
        "description": "13B — noticeably better scene descriptions than 7B",
        "pull_cmd": "ollama pull llava:13b",
        "tags": ["vision"],
    },
    {
        "name": "llava:34b",
        "hf_id": "llava-hf/llava-v1.6-34b-hf",
        "label": "LLaVA 1.6 (34B Q4)",
        "family": "llava",
        "vision": True,
        "params_b": 34.0,
        "vram_gb": 20,
        "tier": "max",
        "backend": "ollama",
        "description": "34B quantized — premium quality, Jetson Thor AGX / RTX 5090",
        "pull_cmd": "ollama pull llava:34b",
        "tags": ["vision", "high-param"],
    },
    # ── Moondream ─────────────────────────────────────────────────────────────
    {
        "name": "moondream:latest",
        "hf_id": "vikhyatk/moondream2",
        "label": "Moondream 2 (1.8B)",
        "family": "moondream",
        "vision": True,
        "params_b": 1.8,
        "vram_gb": 2,
        "tier": "nano",
        "backend": "ollama",
        "description": "Smallest vision model — fast on CPU, great for edge devices",
        "pull_cmd": "ollama pull moondream",
        "tags": ["vision", "edge", "cpu-ok"],
    },
    # ── Qwen2-VL ─────────────────────────────────────────────────────────────
    {
        "name": "qwen2-vl:7b",
        "hf_id": "Qwen/Qwen2-VL-7B-Instruct",
        "label": "Qwen2-VL (7B)",
        "family": "qwen2-vl",
        "vision": True,
        "params_b": 7.0,
        "vram_gb": 6,
        "tier": "mid",
        "backend": "ollama",
        "description": "Strong multi-language vision model, great at dense scene parsing",
        "pull_cmd": "ollama pull qwen2-vl:7b",
        "tags": ["vision", "multilingual"],
    },
    {
        "name": "qwen2-vl:72b-q4_K_M",
        "hf_id": "Qwen/Qwen2-VL-72B-Instruct",
        "label": "Qwen2-VL (72B Q4)",
        "family": "qwen2-vl",
        "vision": True,
        "params_b": 72.0,
        "vram_gb": 40,
        "tier": "max",
        "backend": "ollama",
        "description": "Best-in-class open vision model, Jetson Thor AGX (128 GB)",
        "pull_cmd": "ollama pull qwen2-vl:72b-q4_K_M",
        "tags": ["vision", "high-param", "jetson-thor"],
    },
]


def _is_vision_model(model: dict) -> bool:
    """Heuristic: is this Ollama/vLLM model vision-capable?"""
    name = model.get("id", model.get("name", "")).lower()
    family = ""
    details = model.get("details", {})
    if isinstance(details, dict):
        families = details.get("families") or []
        family = " ".join(families).lower() if families else details.get("family", "").lower()
    combined = f"{name} {family}"
    if any(f in combined for f in _OLLAMA_VISION_FAMILIES):
        return True
    return any(kw in combined for kw in _VISION_KEYWORDS)


# ── Ollama ───────────────────────────────────────────────────────────────────

def _base_url(override: str | None, default: str) -> str:
    """Strip trailing /v1 etc so we always work with the bare base."""
    url = (override or "").strip().rstrip("/")
    if url:
        # Remove /v1 suffix if present — Ollama uses /api/*, vLLM uses /v1/*
        if url.endswith("/v1"):
            url = url[:-3]
        return url
    return default.rstrip("/")


@router.get("/ollama/status")
async def ollama_status(endpoint: str | None = None) -> dict:
    """Check if Ollama is running and return its version.

    Pass ?endpoint=http://jetson-thor:11434 to probe a remote Ollama server.
    """
    base = _base_url(endpoint, OLLAMA_BASE)
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{base}/api/version")
            if r.status_code == 200:
                data = r.json()
                return {"running": True, "endpoint": base, "version": data.get("version")}
    except Exception:
        pass
    return {"running": False, "endpoint": base, "version": None}


@router.get("/ollama/models")
async def ollama_models(endpoint: str | None = None) -> dict:
    """List models available in local Ollama, flagging vision-capable ones.

    Pass ?endpoint=http://jetson-thor:11434 to list a remote Ollama server.
    """
    base = _base_url(endpoint, OLLAMA_BASE)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{base}/api/tags")
            r.raise_for_status()
            raw_models: list[dict] = r.json().get("models", [])
    except Exception:
        return {"running": False, "models": []}

    # Enrich with catalog metadata where available
    catalog_by_name = {m["name"]: m for m in MODEL_CATALOG}

    models = []
    for m in raw_models:
        is_vision = _is_vision_model(m)
        cat = catalog_by_name.get(m["name"], {})
        models.append({
            "name": m["name"],
            "size_gb": round(m.get("size", 0) / 1e9, 1),
            "family": (m.get("details") or {}).get("family", ""),
            "parameter_size": (m.get("details") or {}).get("parameter_size", ""),
            "vision": is_vision,
            # Catalog extras (None if not in catalog)
            "label": cat.get("label"),
            "tier": cat.get("tier"),
            "vram_gb": cat.get("vram_gb"),
            "description": cat.get("description"),
            "tags": cat.get("tags", []),
        })

    # Sort: vision models first, then by name
    models.sort(key=lambda m: (not m["vision"], m["name"]))
    return {"running": True, "models": models}


@router.post("/ollama/pull")
async def ollama_pull_check(body: dict) -> dict:
    """Return pull command for a model (the frontend shows this as a hint)."""
    name = str(body.get("model", "moondream")).strip()
    return {
        "command": f"ollama pull {name}",
        "hint": f"Run in terminal:  ollama pull {name}",
    }


# ── vLLM ────────────────────────────────────────────────────────────────────


def _resolve_vllm_catalog_model(
    model: str,
) -> tuple[str, list[str], dict[str, str], str | None]:
    """Map a UI catalog alias to the Hugging Face model and launch options."""
    entry = _find_vllm_catalog_entry(model)
    if entry:
        return (
            entry["hf_id"],
            list(entry.get("launch_args", [])),
            dict(entry.get("launch_env", {})),
            entry.get("launch_bin"),
        )
    return model.strip(), [], {}, None


def _find_vllm_catalog_entry(model: str) -> dict | None:
    """Return the vLLM catalog entry selected by alias or Hugging Face id."""
    selected = model.strip()
    for entry in MODEL_CATALOG:
        if entry.get("backend") != "vllm":
            continue
        if selected not in {entry["name"], entry["hf_id"]}:
            continue
        return entry
    return None


def _free_gpu_memory_gb() -> float | None:
    """Return max free VRAM across local NVIDIA GPUs, if nvidia-smi is available."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None

    free_mib: list[float] = []
    for line in result.stdout.splitlines():
        raw = line.strip().split(",", maxsplit=1)[0].strip()
        if not raw:
            continue
        try:
            free_mib.append(float(raw))
        except ValueError:
            continue
    if not free_mib:
        return None
    return max(free_mib) / 1024


def _available_system_memory_gb() -> float | None:
    """Return currently available system RAM from /proc/meminfo."""
    try:
        with open("/proc/meminfo") as meminfo:
            for line in meminfo:
                if not line.startswith("MemAvailable:"):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    return float(parts[1]) / (1024 * 1024)
    except (OSError, ValueError):
        return None
    return None


def _ensure_vllm_memory_available(entry: dict | None, caps: HostCapabilities | None = None) -> None:
    if not entry:
        return
    model = entry.get("hf_id") or entry.get("name") or "selected vLLM model"
    required_gb = float(entry.get("vram_gb") or 0)
    if caps is not None and caps.unified_memory:
        # Jetson: weights and KV cache live in system RAM.
        available = caps.ram_available_gb
        if required_gb > 0 and available is not None and available < required_gb:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Not enough available memory to start {model}: needs ~{required_gb:.0f} GB, "
                    f"{available:.0f} GB available. Stop other GPU workloads first."
                ),
            )
        return
    if required_gb > 0:
        free_gb = _free_gpu_memory_gb()
        if free_gb is not None and free_gb < required_gb:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Not enough free GPU memory to start {model}. "
                    f"Catalog estimate is {required_gb:.1f} GiB; "
                    f"currently free is {free_gb:.1f} GiB. "
                    "Stop Ollama/Isaac/CUDA workloads or choose a smaller model."
                ),
            )
    required_ram_gb = float(entry.get("ram_gb") or 0)
    if required_ram_gb <= 0:
        return
    available_ram_gb = _available_system_memory_gb()
    if available_ram_gb is None or available_ram_gb >= required_ram_gb:
        return
    raise HTTPException(
        status_code=409,
        detail=(
            f"Not enough available system RAM to start {model}. "
            f"Catalog estimate is {required_ram_gb:.1f} GiB; "
            f"currently available is {available_ram_gb:.1f} GiB. "
            "Close memory-heavy jobs or use a smaller/quantized model."
        ),
    )


@router.get("/vllm/status")
async def vllm_status(
    endpoint: str | None = None,
    manager: VllmServerManager = Depends(_get_vllm_manager),
) -> dict:
    """Check if a vLLM server is running.

    Pass ?endpoint=http://localhost:8001 (or http://jetson-thor:8001) to probe
    a server on a non-default port or remote host.
    """
    base = _base_url(endpoint, VLLM_BASE)
    managed_status = manager.status()
    managed_for_endpoint = managed_status.get("endpoint") == f"{base}/v1"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{base}/v1/models")
            if r.status_code == 200:
                models = r.json().get("data", [])
                return {
                    "running": True,
                    "endpoint": f"{base}/v1",
                    "model_count": len(models),
                    "managed": managed_for_endpoint,
                    "managed_state": (
                        managed_status.get("state") if managed_for_endpoint else None
                    ),
                    "managed_model": (
                        managed_status.get("model") if managed_for_endpoint else None
                    ),
                    "managed_pid": (
                        managed_status.get("pid") if managed_for_endpoint else None
                    ),
                    "managed_log_tail": (
                        managed_status.get("log_tail", []) if managed_for_endpoint else []
                    ),
                }
    except Exception:
        pass
    return {
        "running": False,
        "endpoint": f"{base}/v1",
        "model_count": 0,
        "managed": managed_for_endpoint,
        "managed_state": managed_status.get("state") if managed_for_endpoint else None,
        "managed_model": managed_status.get("model") if managed_for_endpoint else None,
        "managed_pid": managed_status.get("pid") if managed_for_endpoint else None,
        "managed_log_tail": (
            managed_status.get("log_tail", []) if managed_for_endpoint else []
        ),
    }


def _jetson_launch(entry: dict | None, req: VllmStartRequest) -> DockerLaunch:
    model_dir_name = (entry or {}).get("jetson_model_dir") or req.model.strip().split("/")[-1]
    default_dir = Path(JETSON_MODELS_DIR).expanduser() / model_dir_name
    model_path = req.model_path.strip() or str(default_dir)
    served = (entry or {}).get("served_model_name") or req.model.strip()
    util = req.gpu_memory_utilization
    if entry and entry.get("jetson_gpu_memory_utilization") and req.gpu_memory_utilization == 0.25:
        util = float(entry["jetson_gpu_memory_utilization"])
    extra = tuple(a for a in (entry or {}).get("launch_args", []) if a != "--trust-remote-code")
    return DockerLaunch(
        image=JETSON_VLLM_IMAGE,
        model_path=model_path,
        served_model_name=served,
        gpu_memory_utilization=util,
        max_model_len=req.max_model_len,
        extra_args=extra,
    )


async def _apply_selection(
    store: ConfigStore | None, runtime: Any, *, backend: str, model: str, endpoint: str,
    label: str = "", api_key: str = "", think: bool = False, max_tokens: int = 512,
) -> ModelSettings | None:
    if store is None:
        return None
    current = await store.get_model_settings()
    settings = ModelSettings(
        backend=backend,  # type: ignore[arg-type]
        endpoint=endpoint,
        model=model,
        api_key=api_key,
        think=think,
        max_tokens=max_tokens,
        timeout_s=current.timeout_s,
        label=label or model,
    )
    saved = await store.put_model_settings(settings)
    await store.append_audit("apply_model", "settings", "model", settings.model_dump())
    if runtime is not None:
        await runtime.apply_model_settings()
    return saved


@router.post("/vllm/start")
async def vllm_start(
    req: VllmStartRequest,
    manager: VllmServerManager = Depends(_get_vllm_manager),
    store: ConfigStore = Depends(_get_store),
    runtime: Any = Depends(_get_runtime),
) -> dict:
    """Start an app-managed local vLLM server (binary on workstations, Docker on Jetson)."""
    caps = detect_host()
    launcher = req.launcher
    if launcher == "auto":
        launcher = "docker" if caps.is_jetson else "binary"
    try:
        selected_endpoint = parse_local_vllm_endpoint(req.endpoint)
        entry = _find_vllm_catalog_entry(req.model)
        model, extra_args, extra_env, executable = _resolve_vllm_catalog_model(req.model)
        current = manager.status()
        already_loading = (
            current.get("state") == "starting"
            and current.get("model") in {model, (entry or {}).get("served_model_name")}
            and current.get("endpoint") == selected_endpoint.api_url
        )
        if not already_loading:
            _ensure_vllm_memory_available(entry, caps)
        if launcher == "docker":
            launch = _jetson_launch(entry, req)
            status = manager.start_docker(launch=launch, endpoint=req.endpoint)
            served = launch.served_model_name
        else:
            status = manager.start(
                model=model,
                endpoint=req.endpoint,
                extra_args=extra_args,
                extra_env=extra_env,
                executable=executable,
            )
            served = model
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if runtime is not None:
        runtime.note_server_event("started by operator", model=served, launcher=launcher)
    applied = None
    if req.apply:
        applied = await _apply_selection(
            store, runtime, backend="vllm", model=served,
            endpoint=selected_endpoint.api_url, label=(entry or {}).get("label", served),
        )
    return {"managed": True, "launcher": launcher, "applied": applied, **status}


@router.post("/apply")
async def apply_model(
    req: ApplyModelRequest,
    store: ConfigStore = Depends(_get_store),
    runtime: Any = Depends(_get_runtime),
) -> dict:
    """Select the model the running inference loops use (no server start)."""
    if req.backend not in {"vllm", "ollama", "nim", "mock"}:
        raise HTTPException(status_code=422, detail="backend must be vllm, ollama, nim or mock")
    saved = await _apply_selection(
        store, runtime, backend=req.backend, model=req.model, endpoint=req.endpoint,
        label=req.label, api_key=req.api_key, think=req.think, max_tokens=req.max_tokens,
    )
    return {"applied": saved, "runtime": runtime.model.status() if runtime is not None else None}


@router.post("/vllm/stop")
async def vllm_stop(
    req: VllmStopRequest,
    request: Request,
    manager: VllmServerManager = Depends(_get_vllm_manager),
    runtime: Any = Depends(_get_runtime),
) -> dict:
    """Stop the app-managed vLLM server. Requires confirm=true; the caller is logged."""
    if not req.confirm:
        raise HTTPException(
            status_code=409,
            detail="Stopping the model server affects every app using it; send confirm=true.",
        )
    client = request.client.host if request.client else "unknown"
    logger.warning("vLLM stop requested by %s (%s)", client, req.reason or "no reason given")
    if runtime is not None:
        runtime.note_server_event("stopped by operator", client=client, reason=req.reason)
    return {"managed": True, **manager.stop()}


@router.get("/vllm/models")
async def vllm_models(endpoint: str | None = None) -> dict:
    """List models currently loaded in vLLM.

    Pass ?endpoint=http://localhost:8001 to query a server on a custom port.
    """
    base = _base_url(endpoint, VLLM_BASE)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{base}/v1/models")
            r.raise_for_status()
            raw: list[dict] = r.json().get("data", [])
    except Exception:
        return {"running": False, "models": []}

    models = [
        {
            "name": m["id"],
            "vision": _is_vision_model({"id": m["id"], "name": m["id"]}),
        }
        for m in raw
    ]
    models.sort(key=lambda m: (not m["vision"], m["name"]))
    return {"running": True, "models": models}


# ── Catalog ──────────────────────────────────────────────────────────────────


def _hf_cached(hf_id: str | None) -> bool:
    if not hf_id:
        return False
    hub = Path(os.getenv("HF_HOME", "~/.cache/huggingface")).expanduser() / "hub"
    return (hub / ("models--" + hf_id.replace("/", "--"))).exists()


def _jetson_dir_present(entry: dict) -> bool:
    name = entry.get("jetson_model_dir")
    return bool(name) and (Path(JETSON_MODELS_DIR).expanduser() / str(name)).exists()


def _annotate(
    entry: dict, caps: HostCapabilities, installed: set[str], vllm_loaded: set[str]
) -> dict:
    name = entry["name"]
    hf_id = entry.get("hf_id")
    backend = entry["backend"]
    is_installed = (
        (backend == "ollama" and name in installed)
        or (backend == "vllm" and (name in vllm_loaded or hf_id in vllm_loaded))
        or (backend == "vllm" and (_hf_cached(hf_id) or _jetson_dir_present(entry)))
    )
    required = float(entry.get("vram_gb") or 0)
    if caps.unified_memory:
        required = max(required, float(entry.get("ram_gb") or 0))
    budget = caps.budget_gb()
    reasons: list[str] = []
    if budget is not None and required and required > budget:
        reasons.append(
            f"needs ~{required:.0f} GB, host has {budget:.0f} GB "
            + ("available" if caps.unified_memory else "free VRAM")
        )
    if backend == "ollama" and not caps.has_ollama and not installed:
        reasons.append("Ollama not found on this host")
    if backend == "vllm" and not (caps.has_vllm_binary or caps.has_docker):
        reasons.append("neither vLLM nor Docker found on this host")
    if entry.get("launch_bin") == "vllm-omni" and caps.is_jetson:
        reasons.append("vllm-omni is not available in the Jetson container")
    recommended = (
        (caps.is_jetson and name == "nvidia/cosmos-reason2-2b")
        or (not caps.is_jetson and caps.gpu_name is not None and name == "gemma4:e4b")
    )
    return {
        **entry,
        "installed": is_installed,
        "can_run": not reasons,
        "blocked_reasons": reasons,
        "recommended": recommended,
        "launcher": "docker" if (backend == "vllm" and caps.is_jetson) else backend,
    }


@router.get("/catalog")
async def model_catalog(include_blocked: bool = True) -> dict:
    """Curated vision-model catalog with hardware preflight for this host.

    ``can_run`` is computed from the host's free VRAM (discrete GPU) or
    available RAM (Jetson unified memory) against the catalog estimate.
    """
    caps = detect_host()
    installed: set[str] = set()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{OLLAMA_BASE}/api/tags")
            if r.status_code == 200:
                for m in r.json().get("models", []):
                    installed.add(m["name"])
    except Exception:
        pass

    vllm_loaded: set[str] = set()
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{VLLM_BASE}/v1/models")
            if r.status_code == 200:
                for m in r.json().get("data", []):
                    vllm_loaded.add(m["id"])
    except Exception:
        pass

    entries = [_annotate(m, caps, installed, vllm_loaded) for m in MODEL_CATALOG]
    if not include_blocked:
        entries = [e for e in entries if e["can_run"]]
    entries.sort(
        key=lambda e: (not e["recommended"], not e["can_run"], not e["installed"], e["name"])
    )
    return {"host": caps.to_dict(), "models": entries}
