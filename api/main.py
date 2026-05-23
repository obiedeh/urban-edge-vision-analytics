from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from events.lifecycle import EventStore
from events.schemas import EventType, IncidentStatus, IntersectionIncident, Severity, TrafficEvent
from api.pipeline_manager import PipelineManager
from store.config_store import ConfigStore
from telemetry.metrics import InferenceMetrics
from telemetry.runtime import RuntimeSnapshot
from transports.snapshot import SnapshotTransport
from vision.camera_profiles import CameraConfigError, verify_camera_connection

logger = logging.getLogger(__name__)

# ── Module-level singletons (AGENTS.md: only here) ────────────────────────────
_store = EventStore()
_inference_metrics = InferenceMetrics()
_runtime = RuntimeSnapshot()
_known_cameras: set[str] = set()
_config_store = ConfigStore(os.getenv("STORE_PATH", "store/urbanvision.sqlite"))
_snapshot_transport = SnapshotTransport()
_pipeline_manager = PipelineManager()

_CAMERA_CONFIG_PATH = Path("configs/camera.local.json")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _runtime.started_at = time.time()

    # Initialise SQLite schema
    await _config_store.init()

    adapter = os.getenv("DETECTION_ADAPTER", "mock")

    # Legacy: CAMERA_CONFIG env var → validate connection (backward compat)
    camera_config_env = os.getenv("CAMERA_CONFIG")
    if camera_config_env:
        try:
            connection = verify_camera_connection(
                camera_config_env,
                require_ffplay=os.getenv("CAMERA_REQUIRE_FFPLAY", "0") == "1",
            )
        except CameraConfigError:
            logger.exception("Camera startup validation failed")
            raise
        _runtime.camera_count = 1
        _known_cameras.add(connection.camera_id)
        await _config_store.upsert_camera(
            {
                "id": connection.camera_id,
                "name": connection.camera_id,
                "profile": connection.model_type,
                "rtsp_url": connection.masked_feed_url,
                "detection_adapter": adapter,
            }
        )
        logger.info("Camera validated from env: camera_id=%s", connection.camera_id)

    # Auto-start pipeline if configs/camera.local.json exists on disk
    if _CAMERA_CONFIG_PATH.exists():
        try:
            import json as _json
            _cam_cfg = _json.loads(_CAMERA_CONFIG_PATH.read_text())
            # Prefer adapter saved in the config file; fall back to env var
            _saved_adapter = _cam_cfg.get("detection_adapter", adapter)
            _nvidia_adapters = {"nvidia-nim", "nvidia-vss", "nvidia-cosmos"}

            # Fall back to mock if an NVIDIA adapter is saved but no endpoint is configured
            if _saved_adapter in _nvidia_adapters and not _cam_cfg.get("nvidia_endpoint", "").strip():
                logger.warning(
                    "Adapter '%s' requires an endpoint URL but none is configured — "
                    "falling back to mock adapter to avoid a crash loop.",
                    _saved_adapter,
                )
                _saved_adapter = "mock"

            if _saved_adapter and _saved_adapter != "disabled":
                _saved_synthetic = bool(_cam_cfg.get("synthetic", False))
                logger.info(
                    "Auto-starting pipeline from %s (adapter=%s, synthetic=%s)",
                    _CAMERA_CONFIG_PATH, _saved_adapter, _saved_synthetic,
                )
                _pipeline_manager.start(
                    config_path=str(_CAMERA_CONFIG_PATH),
                    adapter=_saved_adapter,
                    nvidia_endpoint=_cam_cfg.get("nvidia_endpoint") or None,
                    nvidia_api_key=_cam_cfg.get("nvidia_api_key") or None,
                    synthetic=_saved_synthetic,
                    local_model=_cam_cfg.get("local_model") or None,
                    local_endpoint=_cam_cfg.get("local_endpoint") or None,
                )
            else:
                logger.info("Pipeline adapter is 'disabled' — not auto-starting.")
        except Exception:
            logger.exception("Failed to auto-start pipeline")

    yield

    # Graceful shutdown
    _pipeline_manager.stop()


app = FastAPI(
    title="Urban Edge Vision Analytics",
    description="Operational observability API for edge vision inference at smart intersections",
    version="0.1.0",
    lifespan=lifespan,
)

# ── Wire dependency overrides ─────────────────────────────────────────────────

from api.routes import cameras as _cam_routes  # noqa: E402
from api.routes import metrics_extra as _metrics_routes  # noqa: E402
from api.routes import snapshot as _snap_routes  # noqa: E402

app.dependency_overrides[_cam_routes._get_store] = lambda: _config_store
app.dependency_overrides[_cam_routes._get_pipeline] = lambda: _pipeline_manager
app.dependency_overrides[_snap_routes._get_transport] = lambda: _snapshot_transport
app.dependency_overrides[_metrics_routes._get_inference_metrics] = (
    lambda: _inference_metrics
)
app.dependency_overrides[_metrics_routes._get_adapter_name] = lambda: os.getenv(
    "DETECTION_ADAPTER", "mock"
)

# ── Register routers ──────────────────────────────────────────────────────────

from api.routes.artifacts import router as artifacts_router  # noqa: E402
from api.routes.cameras import router as cameras_router  # noqa: E402
from api.routes.metrics_extra import router as metrics_extra_router  # noqa: E402
from api.routes.pipeline import router as pipeline_router  # noqa: E402
from api.routes.pipeline import _get_manager as _pipeline_get_manager  # noqa: E402
from api.routes.snapshot import router as snapshot_router  # noqa: E402
from api.routes.use_cases import router as use_cases_router  # noqa: E402
from api.routes.local_inference import router as local_inference_router  # noqa: E402

app.dependency_overrides[_pipeline_get_manager] = lambda: _pipeline_manager

app.include_router(cameras_router)
app.include_router(use_cases_router)
app.include_router(snapshot_router)
app.include_router(metrics_extra_router)
app.include_router(artifacts_router)
app.include_router(pipeline_router)
app.include_router(local_inference_router)

# ── Existing routes ───────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/runtime")
def runtime():
    return _runtime.to_dict()


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
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def enforce_review_on_critical(self) -> EventIngestRequest:
        if self.severity == Severity.critical:
            self.operator_review_recommended = True
        return self


@app.post("/events", status_code=201)
def ingest_event(req: EventIngestRequest) -> TrafficEvent:
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
        metadata=req.metadata,
    )
    _store.add_event(event)
    _known_cameras.add(event.camera_id)
    _runtime.camera_count = len(_known_cameras)
    _runtime.event_count += 1
    if req.inference_latency_ms is not None:
        _inference_metrics.record(req.inference_latency_ms)
    return event


@app.get("/events")
def list_events(
    camera_id: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> list[TrafficEvent]:
    events = _store.list_events(camera_id=camera_id)
    if cursor:
        try:
            idx = next(i for i, e in enumerate(events) if e.event_id == cursor)
            events = events[idx + 1 :]
        except StopIteration:
            events = []
    return events[:limit]


@app.get("/events/{event_id}")
def get_event(event_id: str) -> TrafficEvent:
    event = _store.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


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
    return incident


# ── Serve compiled frontend (must be last — catch-all for SPA routing) ────────
_web_dist = Path(__file__).parent.parent / "web" / "dist"
if _web_dist.exists():
    # Serve static assets (JS/CSS) under /assets
    app.mount(
        "/assets",
        StaticFiles(directory=str(_web_dist / "assets")),
        name="web-assets",
    )

    @app.get("/", include_in_schema=False)
    @app.get("/{path:path}", include_in_schema=False)
    async def spa_fallback(path: str = "") -> "fastapi.responses.FileResponse":
        from fastapi.responses import FileResponse

        return FileResponse(str(_web_dist / "index.html"))
