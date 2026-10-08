"""Camera CRUD, connection test, USB devices, video uploads, bindings, zones, calibration.

All camera configuration lives in the SQLite config store. Passwords are
encrypted at rest and are never returned; ``has_password`` tells the UI a
secret is stored. Pasted RTSP links are stored and echoed without their
credentials. Uploaded videos arrive as a raw request body (no multipart
parser needed) and are kept next to the store. Changes are applied to the
running EdgeRuntime immediately.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError, model_validator

from packs.base import PackId
from packs.compatibility import IncompatiblePackSelection, validate_pack_set
from store.config_store import ConfigStore
from store.models import CameraIn, CameraRecord, UploadRecord
from vision.camera_profiles import CameraConfigError, get_profile, list_profiles
from vision.probe import probe_stream
from vision.redaction import REDACTOR
from vision.rtsp_url import with_credentials
from vision.uploads import (
    DEFAULT_MAX_BYTES,
    SNIFF_BYTES,
    UploadError,
    check_signature,
    check_size,
    content_type_for,
    probe_video_file,
    safe_filename,
    upload_id_for,
    validate_source_kind,
)
from vision.usb_devices import UsbDevice, list_usb_devices, v4l2_options

router = APIRouter(prefix="/cameras", tags=["cameras"])


# ── Dependencies ──────────────────────────────────────────────────────────────


def _get_store() -> ConfigStore:
    """Overridden in api/main.py after the store is created."""
    raise RuntimeError("Store not initialised")  # pragma: no cover


def _get_runtime() -> Any:
    """Overridden in api/main.py with the EdgeRuntime (may be None in tests)."""
    return None


def _get_upload_limit() -> int:
    """Maximum accepted upload size in bytes; api/main.py supplies the configured value."""
    return DEFAULT_MAX_BYTES


def _get_usb_lister() -> Callable[[], list[UsbDevice]]:
    """Returns the V4L2 enumerator; tests override it with a fake device list."""
    return list_usb_devices


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


# ── USB devices ───────────────────────────────────────────────────────────────


@router.get("/usb-devices")
async def usb_devices(
    lister: Callable[[], list[UsbDevice]] = Depends(_get_usb_lister),
) -> dict:
    """List ``/dev/video*`` capture devices with their names and supported modes.

    An empty list means no camera is plugged in (or none is visible to this
    process); ``note`` carries the message to show. A device that exists but
    cannot be queried is listed with its ``error``.
    """
    devices = await asyncio.to_thread(lister)
    note = None
    if not devices:
        note = (
            "No USB camera found. Plug one in and refresh; it must appear as /dev/video* "
            "and be readable by the user running the API (video group)."
        )
    return {"devices": [d.to_dict() for d in devices], "note": note}


# ── Uploaded videos ───────────────────────────────────────────────────────────


@router.get("/uploads")
async def list_uploads(store: ConfigStore = Depends(_get_store)) -> list[UploadRecord]:
    return await store.list_uploads()


@router.post("/uploads", status_code=201)
async def upload_video(
    request: Request,
    filename: str = Query(..., min_length=1, max_length=255),
    source_kind: str = Query("recorded"),
    store: ConfigStore = Depends(_get_store),
    max_bytes: int = Depends(_get_upload_limit),
) -> UploadRecord:
    """Receive an MP4/MOV/MKV as the raw request body and register it.

    The file is streamed to a temporary name next to the store while its hash
    is computed and the size limit enforced, checked for a matching container
    signature, then opened with PyAV to read its native frame rate, size and
    duration. ``source_kind`` records whether the footage is a real recording
    or generated, and is shown on every event the file produces.
    """
    try:
        kind = validate_source_kind(source_kind)
        safe = safe_filename(filename)
        content_type = content_type_for(safe)
        declared = request.headers.get("content-length", "")
        if declared.isdigit():
            check_size(int(declared), max_bytes)
    except UploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    store.upload_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".upload-", suffix=Path(safe).suffix, dir=store.upload_dir
    )
    tmp = Path(tmp_name)
    digest = hashlib.sha256()
    size = 0
    head = b""
    sniffed = False
    try:
        with os.fdopen(fd, "wb") as fh:
            async for chunk in request.stream():
                if not chunk:
                    continue
                size += len(chunk)
                check_size(size, max_bytes)
                if not sniffed:
                    head += chunk[: SNIFF_BYTES - len(head)]
                    if len(head) >= SNIFF_BYTES:
                        check_signature(head, safe)
                        sniffed = True
                digest.update(chunk)
                await asyncio.to_thread(fh.write, chunk)
        if size == 0:
            raise UploadError("The upload is empty.", 400)
        if not sniffed:
            check_signature(head, safe)
        info = await asyncio.to_thread(probe_video_file, tmp)
        sha = digest.hexdigest()
        upload_id = upload_id_for(safe, sha)
        stored_name = f"{upload_id}{Path(safe).suffix}"
        os.replace(tmp, store.upload_dir / stored_name)
    except UploadError as exc:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    record = UploadRecord(
        id=upload_id, filename=safe, stored_name=stored_name, content_type=content_type,
        size_bytes=size, sha256=sha, source_kind=kind,  # type: ignore[arg-type]
        created_at=datetime.now(UTC).isoformat(), **info.to_dict(),
    )
    saved = await store.add_upload(record)
    await store.append_audit(
        "upload_video", "upload", upload_id,
        {"filename": safe, "size_bytes": size, "sha256": sha, "source_kind": kind},
    )
    return saved


@router.get("/uploads/{upload_id}")
async def get_upload(upload_id: str, store: ConfigStore = Depends(_get_store)) -> UploadRecord:
    record = await store.get_upload(upload_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Upload not found")
    return record


@router.delete("/uploads/{upload_id}", status_code=204)
async def delete_upload(upload_id: str, store: ConfigStore = Depends(_get_store)) -> None:
    """Delete the upload row and its file. Refused (409) while a camera still plays it."""
    record = await store.get_upload(upload_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Upload not found")
    if record.camera_ids:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "upload_in_use",
                "camera_ids": record.camera_ids,
                "message": (
                    "This video is used by camera(s) "
                    + ", ".join(record.camera_ids)
                    + ". Delete or re-point those cameras first."
                ),
            },
        )
    await store.delete_upload(upload_id)
    await store.append_audit("delete_upload", "upload", upload_id, {"filename": record.filename})


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


@router.post("/{camera_id}/restart")
async def restart_camera(
    camera_id: str,
    store: ConfigStore = Depends(_get_store),
    runtime: Any = Depends(_get_runtime),
) -> CameraOut:
    """Restart the capture session: reconnects a stream or replays a play-once video."""
    record = await store.get_camera(camera_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Camera not found")
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


def _probe_payload(
    url: str,
    rtsp_transport: str,
    input_format: str | None = None,
    input_options: dict[str, str] | None = None,
) -> dict:
    result = probe_stream(
        url, rtsp_transport=rtsp_transport, input_format=input_format, input_options=input_options
    )
    data = result.to_dict()
    data["error"] = REDACTOR.redact(data["error"]) if data.get("error") else None
    return data


def _no_stream_note(label: str) -> dict:
    return {"ok": True, "stage": "ok", "error": None, "masked_url": "",
            "note": f"{label} has no stream to probe."}


def _upload_note(upload: UploadRecord | None) -> dict:
    if upload is None:
        return {"ok": False, "stage": "url", "masked_url": "",
                "error": "Uploaded video not found. Upload it first."}
    size = f"{upload.width}x{upload.height}" if upload.width and upload.height else "unknown size"
    fps = f"{upload.fps:g} fps" if upload.fps else "unknown rate"
    dur = f"{upload.duration_s:.1f} s" if upload.duration_s else "unknown length"
    return {
        "ok": True, "stage": "ok", "error": None, "masked_url": upload.filename,
        "width": upload.width, "height": upload.height, "fps": upload.fps, "codec": upload.codec,
        "note": f"{upload.source_kind} footage, {size}, {fps}, {dur}",
    }


class CameraTestIn(CameraIn):
    # When editing a saved camera with the password left blank, the stored
    # (encrypted) password is used so unsaved host/path edits can still be probed.
    camera_id: str | None = None


@router.post("/test")
async def test_unsaved_camera(
    req: CameraTestIn, store: ConfigStore = Depends(_get_store)
) -> dict:
    """Probe the stream, device or file described by the form (not yet saved)."""
    profile = get_profile(req.profile)
    if profile.connector == "usb":
        options = v4l2_options(
            req.capture_width, req.capture_height, req.capture_fps, req.capture_format
        )
        return await asyncio.to_thread(_probe_payload, req.device, "tcp", "v4l2", options)
    if profile.connector == "upload":
        return _upload_note(await store.get_upload(req.upload_id))
    if not profile.requires_host and profile.connector != "rtsp_url":
        return _no_stream_note(profile.label)
    password = req.password
    if not password and req.camera_id:
        saved = await store.get_camera(req.camera_id)
        if saved is None:
            return {"ok": False, "stage": "url", "masked_url": "",
                    "error": f"Camera '{req.camera_id}' is not saved; enter the password."}
        # The stored password is only ever sent to the host it was saved for.
        if (saved.host, saved.port or profile.default_port) != (req.host, req.port):
            return {
                "ok": False, "stage": "url", "masked_url": "",
                "error": (
                    "Host or port differs from the saved camera, so the stored password "
                    "cannot be reused. Enter the password to test the new address."
                ),
            }
        password = await store.get_camera_secret(req.camera_id)
    try:
        if profile.connector == "rtsp_url":
            url = with_credentials(req.source_url, req.username or None, password or None)
        else:
            url = profile.build_url(
                host=req.host, username=req.username or None, password=password or None,
                port=req.port, channel=req.channel, quality=req.stream_quality,
                path=req.stream_path or None,
            )
    except CameraConfigError as exc:
        return {"ok": False, "stage": "url", "error": str(exc), "masked_url": ""}
    REDACTOR.register(password)
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
    if profile.connector == "usb":
        options = v4l2_options(
            record.capture_width, record.capture_height, record.capture_fps, record.capture_format
        )
        return await asyncio.to_thread(_probe_payload, record.device, "tcp", "v4l2", options)
    if profile.connector == "upload":
        return _upload_note(record.upload)
    if not profile.requires_host and profile.connector != "rtsp_url":
        return _no_stream_note(profile.label)
    try:
        url = await store.feed_url(camera_id)
    except CameraConfigError as exc:
        return {"ok": False, "stage": "url", "error": str(exc), "masked_url": ""}
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

        if b.pack_id == PackId.vehicle_count:
            line = b.parameters.get("count_line") or []
            if len(line) < 2:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "missing_prerequisite",
                        "pack_id": str(b.pack_id),
                        "prerequisite": "count_line",
                        "message": (
                            "Pack 'vehicle_count' requires a two-point count_line in its "
                            "parameters (draw it in Studio)."
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
