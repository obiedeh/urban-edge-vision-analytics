from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from api.config import load_settings
from api.vllm_manager import VllmServerManager
from cloud.publisher import build_publisher
from events.schemas import EventType, IncidentStatus, IntersectionIncident, Severity, TrafficEvent
from store.config_store import ConfigStore
from store.event_store import REVIEW_STATUSES, SqliteEventStore
from store.models import CameraIn
from store.secrets import SecretBox
from telemetry.metrics import InferenceMetrics
from telemetry.runtime import RuntimeSnapshot
from telemetry.schemas import EdgeTelemetry
from vision.camera_profiles import _legacy_quality
from vision.redaction import install_logging_filter
from vision.runtime import EdgeRuntime
from vision.webrtc.signaling import close_peer_connections

logger = logging.getLogger(__name__)

# ── Module-level singletons (only here) ────────────────────────────
_settings = load_settings()
_publisher = build_publisher(
    enabled=_settings.cloud.enabled,
    publisher=_settings.cloud.publisher,
    thing_name=_settings.cloud.thing_name,
    schema_version=_settings.cloud.schema_version,
    file_path=_settings.cloud.file_path,
    iot_endpoint=_settings.cloud.iot_endpoint,
    cert_path=_settings.cloud.cert_path,
    key_path=_settings.cloud.key_path,
    ca_path=_settings.cloud.ca_path,
)
_store_path = os.getenv("STORE_PATH", "store/urbanvision.sqlite")
_secrets = SecretBox()
_config_store = ConfigStore(_store_path, secrets=_secrets, upload_dir=_settings.uploads.dir)
_store = SqliteEventStore(_store_path)
_inference_metrics = InferenceMetrics()
_runtime = RuntimeSnapshot()
_edge = EdgeRuntime(
    _config_store,
    _store,
    publisher=_publisher,
    inference_metrics=_inference_metrics,
    runtime_snapshot=_runtime,
)
_vllm_manager = VllmServerManager()
_webrtc_sessions: dict[str, object] = {}
_telemetry_task: asyncio.Task[None] | None = None

_LEGACY_CAMERA_CONFIG = Path("configs/camera.local.json")


def _publish_telemetry() -> None:
    """Serialize the runtime + inference dataclasses through the telemetry contract."""
    _publisher.publish_telemetry(EdgeTelemetry.from_dataclasses(_runtime, _inference_metrics))


async def _telemetry_loop(interval_s: float) -> None:
    while True:
        await asyncio.sleep(interval_s)
        _publish_telemetry()


async def _import_legacy_camera_config() -> None:
    """One-time import of the pre-SQLite ``configs/camera.local.json``.

    The password is encrypted into the store; the file itself is left for the
    operator to delete (it is gitignored) and a warning is logged.
    """
    if not _LEGACY_CAMERA_CONFIG.exists():
        return
    if await _config_store.list_cameras():
        return
    try:
        cfg = json.loads(_LEGACY_CAMERA_CONFIG.read_text(encoding="utf-8"))
        profile = (
            "synthetic" if cfg.get("synthetic") else str(cfg.get("model_type", "generic_rtsp"))
        )
        camera = CameraIn(
            name=str(cfg.get("camera_id") or "imported-camera"),
            profile=profile,
            host=str(cfg.get("host", "")),
            port=int(cfg.get("port") or 0) or None,
            username=str(cfg.get("username", "")),
            password=str(cfg.get("password", "")),
            stream_quality=_legacy_quality(cfg.get("stream")),
            channel=int(cfg.get("channel") or 1),
            rtsp_transport=str(cfg.get("rtsp_transport") or "tcp"),  # type: ignore[arg-type]
            enabled=True,
        )
        record = await _config_store.create_camera(
            camera, camera_id=str(cfg.get("camera_id") or "")
        )
        await _config_store.append_audit(
            "import_legacy_camera", "camera", record.id, {"source": str(_LEGACY_CAMERA_CONFIG)}
        )
        logger.warning(
            "Imported %s into the encrypted config store as camera '%s'. "
            "Delete the file; it holds a plaintext password and is no longer read.",
            _LEGACY_CAMERA_CONFIG, record.id,
        )
    except Exception:
        logger.exception("Failed to import legacy camera config")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _telemetry_task

    install_logging_filter()
    _runtime.started_at = time.time()

    if _settings.cloud.enabled:
        _telemetry_task = asyncio.create_task(
            _telemetry_loop(_settings.cloud.telemetry_interval_s)
        )

    await _config_store.init()
    await _import_legacy_camera_config()
    # A Jetson container started by an earlier API process keeps serving; adopt it.
    _vllm_manager.adopt_container(os.getenv("URBAN_EDGE_VLLM_CONTAINER", "urban-edge-vllm"))
    if os.getenv("URBAN_EDGE_AUTOSTART", "1") != "0":
        await _edge.start()

    yield

    if _telemetry_task is not None:
        _telemetry_task.cancel()
        _telemetry_task = None
    await _edge.stop()
    await close_peer_connections(_webrtc_sessions)
    _vllm_manager.detach()
    _publisher.close()


app = FastAPI(
    title="Urban Edge Vision Analytics",
    description="Operational observability API for edge vision inference at smart intersections",
    version="0.3.0",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Standard 422 body, except camera routes drop the echoed input.

    A rejected camera payload may hold a password or a pasted RTSP link with
    credentials; those must never come back in a response.
    """
    errors = exc.errors()
    if request.url.path.startswith("/cameras"):
        errors = [{k: v for k, v in e.items() if k not in {"input", "url", "ctx"}} for e in errors]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})

# ── Wire dependency overrides ─────────────────────────────────────────────────

from api.routes import cameras as _cam_routes  # noqa: E402
from api.routes import live_results as _live_results_routes  # noqa: E402
from api.routes import local_inference as _local_inference_routes  # noqa: E402
from api.routes import metrics_extra as _metrics_routes  # noqa: E402
from api.routes import settings as _settings_routes  # noqa: E402
from api.routes import stream as _stream_routes  # noqa: E402
from vision.webrtc import signaling as _webrtc_routes  # noqa: E402

app.dependency_overrides[_cam_routes._get_store] = lambda: _config_store
app.dependency_overrides[_cam_routes._get_runtime] = lambda: _edge
app.dependency_overrides[_cam_routes._get_upload_limit] = lambda: _settings.uploads.max_bytes
app.dependency_overrides[_settings_routes._get_store] = lambda: _config_store
app.dependency_overrides[_settings_routes._get_runtime] = lambda: _edge
app.dependency_overrides[_stream_routes._get_runtime] = lambda: _edge
app.dependency_overrides[_local_inference_routes._get_vllm_manager] = lambda: _vllm_manager
app.dependency_overrides[_local_inference_routes._get_store] = lambda: _config_store
app.dependency_overrides[_local_inference_routes._get_runtime] = lambda: _edge
app.dependency_overrides[_live_results_routes._get_broadcaster] = lambda: _edge.broadcaster
app.dependency_overrides[_live_results_routes._get_runtime] = lambda: _edge
app.dependency_overrides[_webrtc_routes._get_runtime] = lambda: _edge
app.dependency_overrides[_webrtc_routes._get_sessions] = lambda: _webrtc_sessions
app.dependency_overrides[_metrics_routes._get_inference_metrics] = lambda: _inference_metrics
app.dependency_overrides[_metrics_routes._get_adapter_name] = (
    lambda: _edge.model.settings.backend
)
app.dependency_overrides[_metrics_routes._get_flow] = lambda: next(
    (r.flow for r in _edge.runners.values()), None
)

# ── Register routers ──────────────────────────────────────────────────────────

from api.routes.artifacts import router as artifacts_router  # noqa: E402
from api.routes.cameras import router as cameras_router  # noqa: E402
from api.routes.live_results import router as live_results_router  # noqa: E402
from api.routes.local_inference import router as local_inference_router  # noqa: E402
from api.routes.metrics_extra import router as metrics_extra_router  # noqa: E402
from api.routes.settings import router as settings_router  # noqa: E402
from api.routes.stream import router as stream_router  # noqa: E402
from api.routes.use_cases import router as use_cases_router  # noqa: E402
from vision.webrtc.signaling import router as webrtc_router  # noqa: E402

app.include_router(cameras_router)
app.include_router(use_cases_router)
app.include_router(stream_router)
app.include_router(settings_router)
app.include_router(metrics_extra_router)
app.include_router(artifacts_router)
app.include_router(local_inference_router)
app.include_router(live_results_router)
app.include_router(webrtc_router)

# ── Core routes ───────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "ok", "version": app.version}


@app.get("/runtime")
def runtime():
    data = _runtime.to_dict()
    data["event_count"] = _store.count_events()
    data["camera_count"] = len(_edge.sessions)
    return data


@app.get("/metrics/inference")
def inference_metrics():
    return _inference_metrics.to_dict()


class EventIngestRequest(BaseModel):
    camera_id: str
    event_type: EventType
    severity: Severity
    vehicle_count: int = 0
    track_ids: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    operator_review_recommended: bool = False
    inference_latency_ms: float | None = None
    vlm_summary: str | None = None
    vlm_reasoning: str | None = None
    vlm_model: str | None = None
    # live_rtsp | usb | browser | uploaded_recorded | uploaded_generated | synthetic
    source_kind: str | None = None
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def enforce_review_on_critical(self) -> EventIngestRequest:
        if self.severity == Severity.critical:
            self.operator_review_recommended = True
        return self


@app.post("/events", status_code=201)
def ingest_event(req: EventIngestRequest) -> dict:
    """External ingest (tests, replay tools). Live pack events are written by the runtime."""
    event = TrafficEvent(
        event_id=str(uuid.uuid4()),
        camera_id=req.camera_id,
        event_type=req.event_type,
        severity=req.severity,
        timestamp=datetime.now(UTC),
        vehicle_count=req.vehicle_count,
        track_ids=req.track_ids,
        confidence=req.confidence,
        operator_review_recommended=req.operator_review_recommended,
        vlm_summary=req.vlm_summary,
        vlm_reasoning=req.vlm_reasoning,
        vlm_model=req.vlm_model,
        source_kind=req.source_kind,
        metadata=req.metadata,
    )
    payload = _store.add_event(event, pack_id=req.metadata.get("pack_id"))
    _publisher.publish_event(event)
    _runtime.event_count += 1
    if req.inference_latency_ms is not None:
        _inference_metrics.record(req.inference_latency_ms)
    return payload


@app.get("/events")
def list_events(
    camera_id: str | None = None,
    cursor: str | None = None,
    before: str | None = None,
    limit: int = 50,
    review_only: bool = False,
    review_status: str | None = None,
    event_type: str | None = None,
) -> list[dict]:
    """Newest first. ``before`` (ISO timestamp) pages backwards; ``cursor`` is the
    legacy event-id form of the same thing."""
    if cursor and not before:
        anchor = _store.get_event(cursor)
        before = anchor["timestamp"] if anchor else None
        if anchor is None:
            return []
    return _store.list_events(
        camera_id=camera_id, limit=limit, before=before, review_only=review_only,
        review_status=review_status, event_type=event_type,
    )


@app.get("/events/review-queue")
def review_queue(status: str = "pending", limit: int = 100) -> dict:
    if status not in REVIEW_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {REVIEW_STATUSES}")
    return {
        "counts": _store.review_counts(),
        "events": _store.list_events(limit=limit, review_only=True, review_status=status),
    }


@app.get("/events/ground-truth")
def ground_truth_events(
    camera_id: str | None = None, since: str | None = None, until: str | None = None
) -> list[dict]:
    """Events the operator annotated with a known pass (pack output vs. ground truth)."""
    return _store.list_ground_truth(camera_id=camera_id, since=since, until=until)


@app.get("/counts")
def all_counts(hours: int = 24) -> dict:
    return _store.count_summary(None, hours=hours)


@app.get("/cameras/{camera_id}/counts")
def camera_counts(camera_id: str, hours: int = 24) -> dict:
    """Vehicle-count totals by class and direction with an hourly breakdown."""
    return _store.count_summary(camera_id, hours=hours)


@app.get("/events/{event_id}/frame.jpg", include_in_schema=True)
def get_event_frame(event_id: str) -> FileResponse:
    """The inference frame captured when a pack event was emitted (if stored)."""
    path = _store.frame_path(event_id)
    if path is None:
        raise HTTPException(status_code=404, detail="No frame stored for this event")
    return FileResponse(str(path), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/events/{event_id}")
def get_event(event_id: str) -> dict:
    event = _store.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


class ReviewRequest(BaseModel):
    status: str
    note: str = ""
    # Operator's description of the known pass behind this event, e.g.
    # "my car, 20 mph" or "full stop". Reported against pack output in run artifacts.
    ground_truth: str | None = None


@app.post("/events/{event_id}/review")
def review_event(event_id: str, req: ReviewRequest) -> dict:
    if req.status not in REVIEW_STATUSES or req.status == "none":
        raise HTTPException(
            status_code=422, detail="status must be pending, confirmed or dismissed"
        )
    updated = _store.review_event(event_id, req.status, req.note, ground_truth=req.ground_truth)
    if not updated:
        raise HTTPException(status_code=404, detail="Event not found")
    return updated


class OpenIncidentRequest(BaseModel):
    camera_id: str
    event_ids: list[str]
    severity: Severity
    summary: str = ""


@app.post("/incidents", status_code=201)
def open_incident(req: OpenIncidentRequest) -> IntersectionIncident:
    incident = _store.open_incident(
        camera_id=req.camera_id,
        event_ids=req.event_ids,
        severity=req.severity,
        summary=req.summary,
    )
    _publisher.publish_incident(incident)
    _runtime.incident_count += 1
    return incident


@app.get("/incidents")
def list_incidents(
    status: IncidentStatus | None = None,
) -> list[IntersectionIncident]:
    return _store.list_incidents(status=status)


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: str) -> IntersectionIncident:
    incident = _store.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


class UpdateIncidentRequest(BaseModel):
    status: IncidentStatus
    notes: str = ""


@app.patch("/incidents/{incident_id}")
def update_incident(
    incident_id: str, req: UpdateIncidentRequest
) -> IntersectionIncident:
    incident = _store.update_incident_status(
        incident_id=incident_id,
        status=req.status,
        notes=req.notes,
    )
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    _publisher.publish_incident(incident)
    return incident


class IncidentTransitionRequest(BaseModel):
    action: str
    note: str = ""


@app.post("/incidents/{incident_id}/transition")
def transition_incident(
    incident_id: str, req: IncidentTransitionRequest
) -> IntersectionIncident:
    _status_map = {
        "review": IncidentStatus.under_review,
        "resolve": IncidentStatus.resolved,
        "dismiss": IncidentStatus.dismissed,
    }
    status = _status_map.get(req.action)
    if not status:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown action '{req.action}'. Use: review, resolve, dismiss.",
        )
    incident = _store.update_incident_status(
        incident_id=incident_id, status=status, notes=req.note
    )
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    _publisher.publish_incident(incident)
    return incident


# ── Serve compiled frontend ───────────────────────────────────────────────────
# Some UI routes share a path with API routes (/cameras, /events). A browser
# navigation asks for text/html, a fetch() does not, so the middleware serves
# the SPA shell for HTML navigations and leaves API calls untouched.
_web_dist = Path(__file__).parent.parent / "web" / "dist"
if _web_dist.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=str(_web_dist / "assets")),
        name="web-assets",
    )

    @app.middleware("http")
    async def spa_for_html_navigation(request: Request, call_next):  # type: ignore[no-untyped-def]
        accept = request.headers.get("accept", "")
        if (
            request.method == "GET"
            and "text/html" in accept
            and not request.url.path.startswith(("/assets", "/docs", "/openapi.json", "/redoc"))
        ):
            return _spa_shell()
        return await call_next(request)

    @app.get("/", include_in_schema=False)
    @app.get("/{path:path}", include_in_schema=False)
    async def spa_fallback(path: str = "") -> FileResponse:
        return _spa_shell()


def _spa_shell() -> FileResponse:
    # The shell shares URLs with JSON routes; without these headers the browser
    # would reuse the cached HTML navigation response for a later fetch().
    return FileResponse(
        str(_web_dist / "index.html"),
        headers={"Cache-Control": "no-store", "Vary": "Accept"},
    )
