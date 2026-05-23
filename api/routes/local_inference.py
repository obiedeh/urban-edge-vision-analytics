"""Routes for querying locally-running inference servers (Ollama, vLLM).

These endpoints are called by the UI adapter switcher to:
  - Check if a local server is reachable
  - List available models
  - Identify which models are vision-capable
  - Return a curated model catalog with hardware requirements

No credentials are required for local servers.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/inference", tags=["local-inference"])

OLLAMA_BASE = "http://localhost:11434"
VLLM_BASE   = "http://localhost:8001"   # default — user can override via ?endpoint=

# Ollama model families that support vision (image input)
_OLLAMA_VISION_FAMILIES = {
    "llava", "moondream", "llava-phi3", "minicpm", "bakllava",
    "llava-llama3", "llama3.2-vision", "granite3", "qwen2-vl",
    "gemma3", "gemma4",                   # Google Gemma 3/4 multimodal
    "cosmos", "cosmos-reason2",           # NVIDIA Cosmos world-model family
    "phi3-vision", "phi4-vision",         # Microsoft Phi vision
    "internvl", "internvl2",              # InternVL series
    "cogvlm", "cogvlm2",
}

# Keywords in model names that indicate vision capability
_VISION_KEYWORDS = {
    "llava", "vision", "moondream", "vl", "visual", "minicpm",
    "cosmos", "cosmos-reason",            # NVIDIA Cosmos
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
        "name": "cosmos-reason2:2b",
        "hf_id": "nvidia/cosmos-reason2-2b",
        "label": "Cosmos Reason 2 (2B)",
        "family": "cosmos-reason2",
        "vision": True,
        "params_b": 2.0,
        "vram_gb": 5,
        "tier": "mid",
        "backend": "ollama",
        "description": "NVIDIA world-model, trained on dashcam/intersection footage",
        "pull_cmd": "ollama pull cosmos-reason2:2b",
        "tags": ["nvidia", "traffic", "world-model"],
    },
    {
        "name": "nvidia/cosmos-reason2-2b",
        "hf_id": "nvidia/cosmos-reason2-2b",
        "label": "Cosmos Reason 2 (2B) via vLLM",
        "family": "cosmos-reason2",
        "vision": True,
        "params_b": 2.0,
        "vram_gb": 5,
        "tier": "mid",
        "backend": "vllm",
        "description": "HuggingFace path — serve with vLLM on RTX 5090",
        "pull_cmd": "vllm serve nvidia/cosmos-reason2-2b --port 8000",
        "tags": ["nvidia", "traffic", "world-model"],
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
        "name": "gemma4:4b-instruct-vision",
        "hf_id": "google/gemma-4-4b-it",
        "label": "Gemma 4 Vision (4B)",
        "family": "gemma4",
        "vision": True,
        "params_b": 4.0,
        "vram_gb": 5,
        "tier": "mid",
        "backend": "ollama",
        "description": "Latest Gemma 4 with vision, fast on any RTX GPU",
        "pull_cmd": "ollama pull gemma4:4b-instruct-vision",
        "tags": ["google", "vision", "latest"],
    },
    {
        "name": "gemma4:27b-instruct-vision-q4_K_M",
        "hf_id": "google/gemma-4-27b-it",
        "label": "Gemma 4 Vision (27B Q4)",
        "family": "gemma4",
        "vision": True,
        "params_b": 27.0,
        "vram_gb": 15,
        "tier": "max",
        "backend": "ollama",
        "description": "Gemma 4 full-size quantized — RTX 5090 / Jetson Thor AGX",
        "pull_cmd": "ollama pull gemma4:27b-instruct-vision-q4_K_M",
        "tags": ["google", "vision", "quantized", "high-param", "latest"],
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

@router.get("/vllm/status")
async def vllm_status(endpoint: str | None = None) -> dict:
    """Check if a vLLM server is running.

    Pass ?endpoint=http://localhost:8001 (or http://jetson-thor:8001) to probe
    a server on a non-default port or remote host.
    """
    base = _base_url(endpoint, VLLM_BASE)
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{base}/v1/models")
            if r.status_code == 200:
                models = r.json().get("data", [])
                return {
                    "running": True,
                    "endpoint": f"{base}/v1",
                    "model_count": len(models),
                }
    except Exception:
        pass
    return {"running": False, "endpoint": f"{base}/v1", "model_count": 0}


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

@router.get("/catalog")
async def model_catalog() -> dict:
    """Return curated vision model catalog with hardware tier info.

    The frontend uses this to show suggested models not yet installed,
    with pull commands and hardware requirements.
    """
    # Check which catalog models are already installed in Ollama
    installed: set[str] = set()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{OLLAMA_BASE}/api/tags")
            if r.status_code == 200:
                for m in r.json().get("models", []):
                    installed.add(m["name"])
    except Exception:
        pass

    # Check which vLLM models are loaded
    vllm_loaded: set[str] = set()
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{VLLM_BASE}/v1/models")
            if r.status_code == 200:
                for m in r.json().get("data", []):
                    vllm_loaded.add(m["id"])
    except Exception:
        pass

    entries = []
    for m in MODEL_CATALOG:
        name = m["name"]
        backend = m["backend"]
        is_installed = (
            (backend == "ollama" and name in installed)
            or (backend == "vllm" and name in vllm_loaded)
        )
        entries.append({**m, "installed": is_installed})

    return {"models": entries}
