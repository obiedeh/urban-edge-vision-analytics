import pytest
from fastapi import HTTPException

from api.routes.local_inference import (
    MODEL_CATALOG,
    _ensure_vllm_memory_available,
    _resolve_vllm_catalog_model,
)


def test_catalog_includes_current_cosmos3_and_gemma4_presets():
    catalog = {entry["name"]: entry for entry in MODEL_CATALOG}

    assert catalog["nvidia/cosmos3-nano-reasoner"]["hf_id"] == "nvidia/Cosmos3-Nano"
    assert catalog["nvidia/cosmos3-nano-reasoner"]["backend"] == "vllm"
    assert catalog["nvidia/cosmos3-nano-reasoner"]["launch_bin"] == "vllm-omni"
    assert catalog["nvidia/cosmos3-nano-reasoner"]["ram_gb"] == 40
    assert "--omni" in catalog["nvidia/cosmos3-nano-reasoner"]["launch_args"]
    assert (
        "--enable-layerwise-offload"
        in catalog["nvidia/cosmos3-nano-reasoner"]["launch_args"]
    )
    assert "--vae-use-slicing" in catalog["nvidia/cosmos3-nano-reasoner"]["launch_args"]
    assert "--vae-use-tiling" in catalog["nvidia/cosmos3-nano-reasoner"]["launch_args"]
    assert (
        "--disable-multithread-weight-load"
        in catalog["nvidia/cosmos3-nano-reasoner"]["launch_args"]
    )
    assert (
        "--diffusion-attention-backend"
        in catalog["nvidia/cosmos3-nano-reasoner"]["launch_args"]
    )
    assert "TORCH_SDPA" in catalog["nvidia/cosmos3-nano-reasoner"]["launch_args"]
    assert "--log-file" in catalog["nvidia/cosmos3-nano-reasoner"]["launch_args"]
    assert (
        catalog["nvidia/cosmos3-nano-reasoner"]["launch_args"].count("--no-guardrails")
        == 1
    )
    assert catalog["nvidia/cosmos3-nano-reasoner"]["launch_env"] == {
        "NIM_MODEL_SIZE": "nano",
    }
    assert catalog["nvidia/cosmos-reason2-2b"]["gated"] is True
    assert catalog["gemma4:e4b"]["hf_id"] == "google/gemma-4-E4B-it"
    assert "quantized" in catalog["gemma4:e4b"]["tags"]
    assert catalog["google/gemma-4-E4B-it"]["backend"] == "vllm"
    assert "--trust-remote-code" in catalog["google/gemma-4-E4B-it"]["launch_args"]
    assert "quantized" in catalog["nvidia/Gemma-4-26B-A4B-NVFP4"]["tags"]


def test_vllm_catalog_alias_resolves_to_hugging_face_launch_config():
    model, args, env, executable = _resolve_vllm_catalog_model(
        "nvidia/cosmos3-nano-reasoner"
    )

    assert model == "nvidia/Cosmos3-Nano"
    assert "--omni" in args
    assert "--enable-layerwise-offload" in args
    assert env == {"NIM_MODEL_SIZE": "nano"}
    assert executable == "vllm-omni"

    model, args, env, executable = _resolve_vllm_catalog_model("google/gemma-4-E4B-it")

    assert model == "google/gemma-4-E4B-it"
    assert args == ["--trust-remote-code"]
    assert env == {}
    assert executable is None


def test_vllm_memory_preflight_rejects_models_that_do_not_fit(monkeypatch):
    catalog = {entry["name"]: entry for entry in MODEL_CATALOG}
    monkeypatch.setattr(
        "api.routes.local_inference._free_gpu_memory_gb",
        lambda: 8.8,
    )

    with pytest.raises(HTTPException) as exc:
        _ensure_vllm_memory_available(catalog["nvidia/cosmos3-nano-reasoner"])

    assert exc.value.status_code == 409
    assert "Not enough free GPU memory" in str(exc.value.detail)
    assert "nvidia/Cosmos3-Nano" in str(exc.value.detail)


def test_vllm_memory_preflight_rejects_low_system_ram(monkeypatch):
    catalog = {entry["name"]: entry for entry in MODEL_CATALOG}
    monkeypatch.setattr(
        "api.routes.local_inference._free_gpu_memory_gb",
        lambda: 32.0,
    )
    monkeypatch.setattr(
        "api.routes.local_inference._available_system_memory_gb",
        lambda: 20.6,
    )

    with pytest.raises(HTTPException) as exc:
        _ensure_vllm_memory_available(catalog["nvidia/cosmos3-nano-reasoner"])

    assert exc.value.status_code == 409
    assert "Not enough available system RAM" in str(exc.value.detail)
    assert "40.0 GiB" in str(exc.value.detail)


def test_vllm_memory_preflight_allows_unknown_gpu_free_memory(monkeypatch):
    catalog = {entry["name"]: entry for entry in MODEL_CATALOG}
    monkeypatch.setattr(
        "api.routes.local_inference._free_gpu_memory_gb",
        lambda: None,
    )
    monkeypatch.setattr(
        "api.routes.local_inference._available_system_memory_gb",
        lambda: None,
    )

    _ensure_vllm_memory_available(catalog["nvidia/cosmos3-nano-reasoner"])
