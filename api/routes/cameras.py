from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from packs.base import PackId
from packs.compatibility import (
    IncompatiblePackSelection,
    validate_pack_set,
)
from api.pipeline_manager import PipelineManager
from store.config_store import ConfigStore

router = APIRouter(prefix="/cameras", tags=["cameras"])

# Path to the local camera config file (relative to CWD, which is project root)
_CAMERA_CONFIG_PATH = Path("configs/camera.local.json")


# ── Dependencies ──────────────────────────────────────────────────────────────


def _get_store() -> ConfigStore:
    """Overridden in api/main.py after the store is created."""
    raise RuntimeError("Store not initialised")  # pragma: no cover


def _get_pipeline() -> PipelineManager:
    """Overridden in api/main.py after the manager is created."""
    raise RuntimeError("PipelineManager not initialised")  # pragma: no cover


# ── Request / response models ─────────────────────────────────────────────────


class BindingIn(BaseModel):
    pack_id: PackId
    parameters: dict = Field(default_factory=dict)
    report_interval_seconds: Annotated[int, Field(ge=2)] = 5

    @model_validator(mode="after")
    def _interval_floor(self) -> BindingIn:
        if self.report_interval_seconds < 2:  # pragma: no cover — ge=2 catches first
            raise ValueError("report_interval_seconds must be >= 2")
        return self


class PutBindingsRequest(BaseModel):
    bindings: list[BindingIn]


class SpeedCalibrationIn(BaseModel):
    gate_a: list[list[float]] = Field(default_factory=list)
    gate_b: list[list[float]] = Field(default_factory=list)
    real_world_distance_m: float = Field(gt=0)
    homography: Any = None


class StopZoneIn(BaseModel):
    polygon: list[list[float]]
    approach_direction: str = "N"
    compliance_thresholds: dict = Field(default_factory=dict)


# ── Camera config file models ─────────────────────────────────────────────────

SUPPORTED_MODEL_TYPES = [
    "hikvision", "tapo", "dahua", "amcrest",
    "axis", "reolink", "generic_rtsp", "unifi_protect", "http_mjpeg",
]

SUPPORTED_ADAPTERS = ["mock", "ollama", "vllm", "nvidia-nim", "nvidia-vss", "nvidia-cosmos", "disabled"]


class CameraConfigIn(BaseModel):
    camera_id: str | None = None
    model_type: str = "hikvision"
    host: str = Field(default="", description="Camera IP address or hostname (not required for synthetic mode)")
    port: int = Field(554, ge=1, le=65535)
    stream: str = "01"
    channel: int = Field(1, ge=1)
    username: str = ""
    password: str = ""
    rtsp_transport: str = "tcp"
    detection_adapter: str = "mock"       # which inference engine to use
    nvidia_endpoint: str = ""             # NVIDIA NIM / VSS / Cosmos endpoint URL
    nvidia_api_key: str = ""              # API key (not saved in plaintext — masked like password)
    synthetic: bool = False               # True = no real camera, generate synthetic frames

    @model_validator(mode="after")
    def _validate(self) -> "CameraConfigIn":
        if self.model_type not in SUPPORTED_MODEL_TYPES:
            raise ValueError(
                f"Unsupported model_type '{self.model_type}'. "
                f"Supported: {', '.join(SUPPORTED_MODEL_TYPES)}"
            )
        if self.detection_adapter not in SUPPORTED_ADAPTERS:
            raise ValueError(
                f"Unsupported detection_adapter '{self.detection_adapter}'. "
                f"Supported: {', '.join(SUPPORTED_ADAPTERS)}"
            )
        if not self.synthetic and not self.host.strip():
            raise ValueError("host is required for live cameras (set synthetic=true for demo mode)")
        return self


class AdapterSwitchIn(BaseModel):
    detection_adapter: str = "mock"
    nvidia_endpoint: str = ""
    nvidia_api_key: str = ""
    local_model: str = ""      # model name for ollama / vllm adapters
    local_endpoint: str = ""   # custom host:port for ollama / vllm (e.g. http://localhost:8001/v1)


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/config")
async def get_camera_config() -> dict:
    """Return the current camera.local.json contents (password masked)."""
    if not _CAMERA_CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail="No camera config file found")
    try:
        config: dict = json.loads(_CAMERA_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read config: {exc}") from exc
    # Mask credentials in the response
    if "password" in config:
        config["password"] = "••••••••" if config["password"] else ""
    if "nvidia_api_key" in config:
        config["nvidia_api_key"] = "••••••••" if config["nvidia_api_key"] else ""
    return config


@router.post("/config", status_code=201)
async def save_camera_config(
    req: CameraConfigIn,
    store: ConfigStore = Depends(_get_store),
    pipeline: PipelineManager = Depends(_get_pipeline),
) -> dict:
    """Write camera connection details to configs/camera.local.json and upsert into the store."""
    safe_host = req.host.strip().replace(".", "-")
    camera_id = (req.camera_id or "").strip() or f"{req.model_type}-{safe_host}"

    # If password is blank, preserve the existing password from the config file (edit mode).
    resolved_password = req.password
    if not resolved_password and _CAMERA_CONFIG_PATH.exists():
        try:
            existing = json.loads(_CAMERA_CONFIG_PATH.read_text(encoding="utf-8"))
            resolved_password = existing.get("password", "")
        except Exception:
            pass

    # Preserve existing nvidia_api_key if blank (same pattern as password)
    resolved_nvidia_key = req.nvidia_api_key
    if not resolved_nvidia_key and _CAMERA_CONFIG_PATH.exists():
        try:
            existing = json.loads(_CAMERA_CONFIG_PATH.read_text(encoding="utf-8"))
            resolved_nvidia_key = existing.get("nvidia_api_key", "")
        except Exception:
            pass

    config_dict = {
        "camera_id": camera_id,
        "model_type": req.model_type,
        "host": req.host.strip(),
        "port": req.port,
        "stream": req.stream,
        "channel": req.channel,
        "username": req.username,
        "password": resolved_password,
        "rtsp_transport": req.rtsp_transport,
        "detection_adapter": req.detection_adapter,
        "nvidia_endpoint": req.nvidia_endpoint.strip(),
        "nvidia_api_key": resolved_nvidia_key,
        "synthetic": req.synthetic,
        "local_model": "",   # set via adapter switcher; not collected from camera setup form
    }

    _CAMERA_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CAMERA_CONFIG_PATH.write_text(
        json.dumps(config_dict, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    masked_url = (
        f"rtsp://***:***@{req.host.strip()}:{req.port}"
        f"/stream-{req.stream}-ch{req.channel}"
    )
    await store.upsert_camera(
        {
            "id": camera_id,
            "name": camera_id,
            "profile": req.model_type,
            "rtsp_url": masked_url,
            "detection_adapter": req.detection_adapter,
            "synthetic": req.synthetic,
            "enabled": True,
        }
    )
    await store.append_audit(
        action="save_camera_config",
        target_kind="camera",
        target_id=camera_id,
        payload={
            k: v for k, v in config_dict.items()
            if k not in ("password", "nvidia_api_key")
        },
    )

    # Start or stop pipeline based on adapter choice
    if req.detection_adapter == "disabled":
        pipeline.stop()
        pipeline_state = "stopped"
    else:
        pipeline.start(
            config_path=str(_CAMERA_CONFIG_PATH),
            adapter=req.detection_adapter,
            nvidia_endpoint=req.nvidia_endpoint.strip() or None,
            nvidia_api_key=resolved_nvidia_key or None,
            synthetic=req.synthetic,
        )
        pipeline_state = "started"

    return {
        "camera_id": camera_id,
        "model_type": req.model_type,
        "host": req.host.strip(),
        "port": req.port,
        "detection_adapter": req.detection_adapter,
        "status": "saved",
        "pipeline": pipeline_state,
    }


@router.delete("/config", status_code=204)
async def delete_camera_config(
    pipeline: PipelineManager = Depends(_get_pipeline),
) -> None:
    """Remove configs/camera.local.json and stop the pipeline."""
    if not _CAMERA_CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail="No camera config file found")
    pipeline.stop()
    _CAMERA_CONFIG_PATH.unlink()


@router.post("/config/adapter")
async def switch_adapter(
    req: AdapterSwitchIn,
    pipeline: PipelineManager = Depends(_get_pipeline),
) -> dict:
    """Switch the inference adapter (or stop it) without re-saving camera credentials."""
    if not _CAMERA_CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail="No camera config file found. Save camera config first.")

    # Persist adapter choice in config file
    config = json.loads(_CAMERA_CONFIG_PATH.read_text(encoding="utf-8"))
    config["detection_adapter"] = req.detection_adapter
    if req.nvidia_endpoint:
        config["nvidia_endpoint"] = req.nvidia_endpoint.strip()
    if req.nvidia_api_key:
        config["nvidia_api_key"] = req.nvidia_api_key
    if req.local_model:
        config["local_model"] = req.local_model.strip()
    if req.local_endpoint:
        config["local_endpoint"] = req.local_endpoint.strip()
    _CAMERA_CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")

    if req.detection_adapter == "disabled":
        pipeline.stop()
        return {"detection_adapter": "disabled", "pipeline": "stopped"}

    # Resolve nvidia_api_key — keep existing if blank
    resolved_key = req.nvidia_api_key or config.get("nvidia_api_key", "")
    # Resolve model and endpoint — prefer request value, then whatever is saved in config
    resolved_model    = req.local_model.strip()    or config.get("local_model", "")    or None
    resolved_local_ep = req.local_endpoint.strip() or config.get("local_endpoint", "") or None

    pipeline.start(
        config_path=str(_CAMERA_CONFIG_PATH),
        adapter=req.detection_adapter,
        nvidia_endpoint=req.nvidia_endpoint.strip() or config.get("nvidia_endpoint") or None,
        nvidia_api_key=resolved_key or None,
        local_model=resolved_model,
        local_endpoint=resolved_local_ep,
    )
    return {"detection_adapter": req.detection_adapter, "pipeline": "started"}


@router.post("/config/test")
async def test_camera_config(req: CameraConfigIn) -> dict:
    """Validate that the given parameters form a legal RTSP URL (no network call — fast check)."""
    import socket

    from vision.camera_profiles import CAMERA_PROFILES, CameraConfigError

    safe_host = req.host.strip().replace(".", "-")
    camera_id = (req.camera_id or "").strip() or f"{req.model_type}-{safe_host}"

    # 1. Profile validation
    profile = CAMERA_PROFILES.get(req.model_type)
    if profile is None:
        return {
            "ok": False,
            "camera_id": camera_id,
            "error": f"Unsupported model_type '{req.model_type}'",
            "stage": "profile",
        }

    # 2. Build URL (validates username/password requirements)
    resolved_password = req.password
    if not resolved_password and _CAMERA_CONFIG_PATH.exists():
        try:
            existing = json.loads(_CAMERA_CONFIG_PATH.read_text(encoding="utf-8"))
            resolved_password = existing.get("password", "")
        except Exception:
            pass
    try:
        feed_url = profile.build_url(
            host=req.host.strip(),
            username=req.username or None,
            password=resolved_password or None,
            port=req.port,
            channel=req.channel,
            stream=req.stream,
        )
    except CameraConfigError as exc:
        return {"ok": False, "camera_id": camera_id, "error": str(exc), "stage": "url"}

    # 3. TCP reachability check (port open within 2 s)
    reachable = False
    reach_error = ""
    try:
        with socket.create_connection((req.host.strip(), req.port), timeout=2):
            reachable = True
    except OSError as exc:
        reach_error = str(exc)

    from vision.camera_profiles import _mask_url  # noqa: PLC0415

    return {
        "ok": reachable,
        "camera_id": camera_id,
        "masked_url": _mask_url(feed_url),
        "reachable": reachable,
        "reach_error": reach_error if not reachable else None,
        "stage": "reachability",
    }


@router.get("")
async def list_cameras(store: ConfigStore = Depends(_get_store)) -> list[dict]:
    return await store.list_cameras()


@router.get("/{camera_id}/bindings")
async def get_bindings(
    camera_id: str,
    store: ConfigStore = Depends(_get_store),
) -> list[dict]:
    rows = await store.get_bindings(camera_id)
    # Deserialise parameters_json for the response
    result = []
    for row in rows:
        r = dict(row)
        r["parameters"] = json.loads(r.pop("parameters_json", "{}"))
        result.append(r)
    return result


@router.put("/{camera_id}/bindings")
async def put_bindings(
    camera_id: str,
    req: PutBindingsRequest,
    store: ConfigStore = Depends(_get_store),
) -> dict:
    """Replace all bindings for a camera.

    Returns 422 with one of:
      - error: "incompatible_pack_selection"
      - error: "missing_prerequisite"
      - error: "invalid_report_interval"
    """
    # 1. Validate report_interval (Pydantic ge=2 handles it, but we surface a
    #    custom error code for the API contract)
    for b in req.bindings:
        if b.report_interval_seconds < 2:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "invalid_report_interval",
                    "message": "report_interval_seconds must be >= 2",
                    "minimum": 2,
                },
            )

    # 2. Compatibility rule
    pack_ids = [b.pack_id for b in req.bindings]
    try:
        validate_pack_set(pack_ids)
    except IncompatiblePackSelection as exc:
        allowed = [sorted(str(p) for p in s) for s in exc.allowed]
        raise HTTPException(
            status_code=422,
            detail={
                "error": "incompatible_pack_selection",
                "message": str(exc),
                "selected": [str(p) for p in exc.selected],
                "allowed_sets": allowed,
            },
        ) from exc

    # 3. Per-pack prerequisites
    for b in req.bindings:
        if b.pack_id == PackId.speed_violation:
            cal = await store.get_speed_calibration(camera_id)
            if not cal:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "missing_prerequisite",
                        "pack_id": str(b.pack_id),
                        "prerequisite": "speed_calibration",
                        "message": (
                            "Pack 'speed_violation' requires a speed calibration. "
                            f"POST /cameras/{camera_id}/speed-calibration first."
                        ),
                    },
                )
        if b.pack_id == PackId.stop_sign:
            zone = await store.get_stop_zone(camera_id)
            if not zone:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "missing_prerequisite",
                        "pack_id": str(b.pack_id),
                        "prerequisite": "stop_zone",
                        "message": (
                            "Pack 'stop_sign' requires a stop zone. "
                            f"PUT /cameras/{camera_id}/stop-zone first."
                        ),
                    },
                )

    # 4. Persist
    binding_rows = [
        {
            "pack_id": str(b.pack_id),
            "parameters": b.parameters,
            "report_interval_seconds": b.report_interval_seconds,
        }
        for b in req.bindings
    ]
    await store.replace_bindings(camera_id, binding_rows)
    await store.append_audit(
        action="replace_bindings",
        target_kind="camera",
        target_id=camera_id,
        payload={"pack_ids": [str(b.pack_id) for b in req.bindings]},
    )

    return {"camera_id": camera_id, "bindings": len(req.bindings), "status": "saved"}


@router.post("/{camera_id}/speed-calibration", status_code=201)
async def save_speed_calibration(
    camera_id: str,
    req: SpeedCalibrationIn,
    store: ConfigStore = Depends(_get_store),
) -> dict:
    await store.save_speed_calibration(camera_id, req.model_dump())
    await store.append_audit(
        action="save_speed_calibration",
        target_kind="camera",
        target_id=camera_id,
        payload=req.model_dump(),
    )
    return {"camera_id": camera_id, "status": "saved"}


@router.get("/{camera_id}/speed-calibration")
async def get_speed_calibration(
    camera_id: str,
    store: ConfigStore = Depends(_get_store),
) -> dict:
    cal = await store.get_speed_calibration(camera_id)
    if not cal:
        raise HTTPException(status_code=404, detail="No speed calibration found")
    cal["gate_a"] = json.loads(cal.pop("gate_a_json", "{}"))
    cal["gate_b"] = json.loads(cal.pop("gate_b_json", "{}"))
    if cal.get("homography_json"):
        cal["homography"] = json.loads(cal.pop("homography_json"))
    else:
        cal.pop("homography_json", None)
        cal["homography"] = None
    return cal


@router.put("/{camera_id}/stop-zone", status_code=200)
async def put_stop_zone(
    camera_id: str,
    req: StopZoneIn,
    store: ConfigStore = Depends(_get_store),
) -> dict:
    await store.save_stop_zone(camera_id, req.model_dump())
    await store.append_audit(
        action="save_stop_zone",
        target_kind="camera",
        target_id=camera_id,
        payload=req.model_dump(),
    )
    return {"camera_id": camera_id, "status": "saved"}


@router.get("/{camera_id}/stop-zone")
async def get_stop_zone(
    camera_id: str,
    store: ConfigStore = Depends(_get_store),
) -> dict:
    zone = await store.get_stop_zone(camera_id)
    if not zone:
        raise HTTPException(status_code=404, detail="No stop zone found")
    zone["polygon"] = json.loads(zone.pop("polygon_json", "[]"))
    zone["compliance_thresholds"] = json.loads(
        zone.pop("compliance_threshold_json", "{}")
    )
    return zone
