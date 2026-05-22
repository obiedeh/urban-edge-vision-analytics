from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from packs.base import PackId
from packs.compatibility import (
    IncompatiblePackSelection,
    validate_pack_set,
)
from store.config_store import ConfigStore

router = APIRouter(prefix="/cameras", tags=["cameras"])


# ── Dependency ────────────────────────────────────────────────────────────────


def _get_store() -> ConfigStore:
    """Overridden in api/main.py after the store is created."""
    raise RuntimeError("Store not initialised")  # pragma: no cover


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
    gate_a: dict = Field(default_factory=dict)
    gate_b: dict = Field(default_factory=dict)
    real_world_distance_m: float = Field(gt=0)
    homography: Any = None


class StopZoneIn(BaseModel):
    polygon: list[list[float]]
    approach_direction: str = "N"
    compliance_thresholds: dict = Field(default_factory=dict)


# ── Routes ────────────────────────────────────────────────────────────────────


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
