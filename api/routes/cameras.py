"""Camera CRUD, connection test, pack bindings, zones and calibration.

All camera configuration lives in the SQLite config store. Passwords are
encrypted at rest and are never returned; ``has_password`` tells the UI a
secret is stored. Changes are applied to the running EdgeRuntime immediately.
"""
from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError, model_validator

from packs.base import PackId
from packs.compatibility import IncompatiblePackSelection, validate_pack_set
from store.config_store import ConfigStore
from store.models import CameraIn, CameraRecord
from vision.camera_profiles import CameraConfigError, get_profile, list_profiles
from vision.probe import probe_stream
from vision.redaction import REDACTOR

router = APIRouter(prefix="/cameras", tags=["cameras"])


# ── Dependencies ──────────────────────────────────────────────────────────────


def _get_store() -> ConfigStore:
    """Overridden in api/main.py after the store is created."""
    raise RuntimeError("Store not initialised")  # pragma: no cover


def _get_runtime() -> Any:
    """Overridden in api/main.py with the EdgeRuntime (may be None in tests)."""
    return None


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
    gate_a: Any = Field(default_factory=list)
    gate_b: Any = Field(default_factory=list)
    real_world_distance_m: float = Field(gt=0)
    posted_speed_kph: float = Field(default=50.0, gt=0)
    homography: Any = None


class StopZoneIn(BaseModel):
    polygon: list[list[float]]
    approach_direction: str = "N"
    compliance_thresholds: dict = Field(default_factory=dict)


class EnableIn(BaseModel):
    enabled: bool


class CameraOut(CameraRecord):
    runtime: dict[str, Any] | None = None


def _with_runtime(record: CameraRecord, runtime: Any) -> CameraOut:
    status = None
    if runtime is not None:
        session = runtime.session(record.id)
        if session is not None:
            status = session.status()
    return CameraOut(**record.model_dump(), runtime=status)


# ── Profiles ──────────────────────────────────────────────────────────────────


@router.get("/profiles")
async def camera_profiles() -> list[dict]:
    return list_profiles()


# ── CRUD ──────────────────────────────────────────────────────────────────────


@router.get("")
async def list_cameras(
    store: ConfigStore = Depends(_get_store),
    runtime: Any = Depends(_get_runtime),
) -> list[CameraOut]:
    return [_with_runtime(c, runtime) for c in await store.list_cameras()]


@router.post("", status_code=201)
async def create_camera(
    req: CameraIn,
    store: ConfigStore = Depends(_get_store),
    runtime: Any = Depends(_get_runtime),
) -> CameraOut:
    try:
        record = await store.create_camera(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await store.append_audit("create_camera", "camera", record.id, req.model_dump())
    if runtime is not None:
        await runtime.refresh_camera(record.id)
    return _with_runtime(record, runtime)


@router.get("/{camera_id}")
async def get_camera(
    camera_id: str,
    store: ConfigStore = Depends(_get_store),
    runtime: Any = Depends(_get_runtime),
) -> CameraOut:
    record = await store.get_camera(camera_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    return _with_runtime(record, runtime)


@router.put("/{camera_id}")
async def update_camera(
    camera_id: str,
    req: CameraIn,
    store: ConfigStore = Depends(_get_store),
    runtime: Any = Depends(_get_runtime),
) -> CameraOut:
    try:
        record = await store.update_camera(camera_id, req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    await store.append_audit("update_camera", "camera", camera_id, req.model_dump())
    if runtime is not None:
        await runtime.refresh_camera(camera_id)
    return _with_runtime(record, runtime)


@router.post("/{camera_id}/enabled")
async def set_enabled(
    camera_id: str,
    req: EnableIn,
    store: ConfigStore = Depends(_get_store),
    runtime: Any = Depends(_get_runtime),
) -> CameraOut:
    record = await store.set_camera_enabled(camera_id, req.enabled)
    if record is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    await store.append_audit("set_camera_enabled", "camera", camera_id, {"enabled": req.enabled})
    if runtime is not None:
        await runtime.refresh_camera(camera_id)
    return _with_runtime(record, runtime)


@router.delete("/{camera_id}", status_code=204)
async def delete_camera(
    camera_id: str,
    store: ConfigStore = Depends(_get_store),
    runtime: Any = Depends(_get_runtime),
) -> None:
    if runtime is not None:
        await runtime.remove_camera(camera_id)
    deleted = await store.delete_camera(camera_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Camera not found")
    await store.append_audit("delete_camera", "camera", camera_id, {})


# ── Test connection ───────────────────────────────────────────────────────────


def _probe_payload(url: str, rtsp_transport: str) -> dict:
    result = probe_stream(url, rtsp_transport=rtsp_transport)
    data = result.to_dict()
    data["error"] = REDACTOR.redact(data["error"]) if data.get("error") else None
    return data


class CameraTestIn(CameraIn):
    # When editing a saved camera with the password left blank, the stored
    # (encrypted) password is used so unsaved host/path edits can still be probed.
    camera_id: str | None = None


@router.post("/test")
async def test_unsaved_camera(
    req: CameraTestIn, store: ConfigStore = Depends(_get_store)
) -> dict:
    """Probe the stream described by the form (not yet saved)."""
    profile = get_profile(req.profile)
    if not profile.requires_host:
        return {"ok": True, "stage": "ok", "error": None, "masked_url": "",
                "note": f"{profile.label} has no stream to probe."}
    password = req.password
    if not password and req.camera_id:
        password = await store.get_camera_secret(req.camera_id)
    try:
        url = profile.build_url(
            host=req.host, username=req.username or None, password=password or None,
            port=req.port, channel=req.channel, quality=req.stream_quality,
            path=req.stream_path or None,
        )
    except CameraConfigError as exc:
        return {"ok": False, "stage": "url", "error": str(exc), "masked_url": ""}
    REDACTOR.register(password)
    import asyncio

    return await asyncio.to_thread(_probe_payload, url, req.rtsp_transport)


@router.post("/{camera_id}/test")
async def test_saved_camera(
    camera_id: str,
    store: ConfigStore = Depends(_get_store),
) -> dict:
    """Probe a saved camera using its stored (encrypted) credentials."""
    record = await store.get_camera(camera_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    profile = get_profile(record.profile)
    if not profile.requires_host:
        return {"ok": True, "stage": "ok", "error": None, "masked_url": "",
                "note": f"{profile.label} has no stream to probe."}
    try:
        url = await store.feed_url(camera_id)
    except CameraConfigError as exc:
        return {"ok": False, "stage": "url", "error": str(exc), "masked_url": ""}
    import asyncio

    return await asyncio.to_thread(_probe_payload, url, record.rtsp_transport)


# ── Bindings ──────────────────────────────────────────────────────────────────


@router.get("/{camera_id}/bindings")
async def get_bindings(
    camera_id: str,
    store: ConfigStore = Depends(_get_store),
) -> list[dict]:
    rows = await store.get_bindings(camera_id)
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
    runtime: Any = Depends(_get_runtime),
) -> dict:
    """Replace all bindings for a camera.

    Returns 422 with one of:
      - error: "incompatible_pack_selection"
      - error: "missing_prerequisite"
      - error: "invalid_report_interval"
    """
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
    if runtime is not None:
        await runtime.refresh_bindings(camera_id)
    return {"camera_id": camera_id, "bindings": len(req.bindings), "status": "saved"}


@router.post("/{camera_id}/speed-calibration", status_code=201)
async def save_speed_calibration(
    camera_id: str,
    req: SpeedCalibrationIn,
    store: ConfigStore = Depends(_get_store),
    runtime: Any = Depends(_get_runtime),
) -> dict:
    await store.save_speed_calibration(camera_id, req.model_dump())
    await store.append_audit("save_speed_calibration", "camera", camera_id, req.model_dump())
    if runtime is not None:
        await runtime.refresh_bindings(camera_id)
    return {"camera_id": camera_id, "status": "saved"}


@router.get("/{camera_id}/speed-calibration")
async def get_speed_calibration(
    camera_id: str,
    store: ConfigStore = Depends(_get_store),
) -> dict:
    cal = await store.get_speed_calibration(camera_id)
    if not cal:
        raise HTTPException(status_code=404, detail="No speed calibration found")
    cal["gate_a"] = json.loads(cal.pop("gate_a_json", "[]"))
    cal["gate_b"] = json.loads(cal.pop("gate_b_json", "[]"))
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
    runtime: Any = Depends(_get_runtime),
) -> dict:
    await store.save_stop_zone(camera_id, req.model_dump())
    await store.append_audit("save_stop_zone", "camera", camera_id, req.model_dump())
    if runtime is not None:
        await runtime.refresh_bindings(camera_id)
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
    zone["compliance_thresholds"] = json.loads(zone.pop("compliance_threshold_json", "{}"))
    return zone


__all__ = ["router", "ValidationError"]
