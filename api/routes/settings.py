"""Runtime settings: model endpoint, inference cadence/resolution/prompt, live view."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from store.config_store import ConfigStore
from store.models import InferenceSettings, LiveSettings, ModelSettings
from vision.host_capabilities import default_model_for, detect_host
from vision.prompt_presets import list_presets

router = APIRouter(tags=["settings"])


def _get_store() -> ConfigStore:
    raise RuntimeError("Store not initialised")  # pragma: no cover


def _get_runtime() -> Any:
    return None


@router.get("/settings/model")
async def get_model_settings(store: ConfigStore = Depends(_get_store)) -> ModelSettings:
    return await store.get_model_settings()


@router.put("/settings/model")
async def put_model_settings(
    req: ModelSettings,
    store: ConfigStore = Depends(_get_store),
    runtime: Any = Depends(_get_runtime),
) -> ModelSettings:
    saved = await store.put_model_settings(req)
    await store.append_audit("put_model_settings", "settings", "model", req.model_dump())
    if runtime is not None:
        await runtime.apply_model_settings()
    return saved


@router.get("/settings/model/default")
async def model_default() -> dict:
    caps = detect_host()
    return {"host": caps.to_dict(), "default": default_model_for(caps)}


@router.get("/settings/inference")
async def get_inference_settings(store: ConfigStore = Depends(_get_store)) -> InferenceSettings:
    return await store.get_inference_settings()


@router.put("/settings/inference")
async def put_inference_settings(
    req: InferenceSettings,
    store: ConfigStore = Depends(_get_store),
    runtime: Any = Depends(_get_runtime),
) -> InferenceSettings:
    if req.prompt_preset not in {p["id"] for p in list_presets()}:
        raise HTTPException(status_code=422, detail=f"Unknown prompt preset '{req.prompt_preset}'")
    saved = await store.put_inference_settings(req)
    await store.append_audit("put_inference_settings", "settings", "inference", req.model_dump())
    if runtime is not None:
        await runtime.apply_inference_settings()
    return saved


@router.get("/settings/prompt-presets")
async def prompt_presets() -> list[dict[str, str]]:
    return list_presets()


@router.get("/settings/live")
async def get_live_settings(store: ConfigStore = Depends(_get_store)) -> LiveSettings:
    return await store.get_live_settings()


@router.put("/settings/live")
async def put_live_settings(
    req: LiveSettings, store: ConfigStore = Depends(_get_store)
) -> LiveSettings:
    return await store.put_live_settings(req)


@router.get("/runtime/status")
async def runtime_status(runtime: Any = Depends(_get_runtime)) -> dict:
    if runtime is None:
        return {"cameras": [], "model": None, "host": detect_host().to_dict()}
    return runtime.status()


@router.get("/host/capabilities")
async def host_capabilities() -> dict:
    return detect_host().to_dict()
