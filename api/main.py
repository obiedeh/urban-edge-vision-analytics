from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from events.lifecycle import EventStore
from events.schemas import EventType, IncidentStatus, IntersectionIncident, Severity, TrafficEvent
from telemetry.metrics import InferenceMetrics
from telemetry.runtime import RuntimeSnapshot
from vision.camera_profiles import CameraConfigError, verify_camera_connection

logger = logging.getLogger(__name__)

_store = EventStore()
_inference_metrics = InferenceMetrics()
_runtime = RuntimeSnapshot()
_known_cameras: set[str] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _runtime.started_at = time.time()
    camera_config = os.getenv("CAMERA_CONFIG")
    if camera_config:
        try:
            connection = verify_camera_connection(
                camera_config,
                require_ffplay=os.getenv("CAMERA_REQUIRE_FFPLAY", "0") == "1",
            )
        except CameraConfigError:
            logger.exception("Camera startup validation failed")
            raise
        _runtime.camera_count = 1
        _known_cameras.add(connection.camera_id)
        logger.info(
            "Camera startup validation passed: camera_id=%s model_type=%s host=%s feed_url=%s",
            connection.camera_id,
            connection.model_type,
            connection.host,
            connection.masked_feed_url,
        )
    yield


app = FastAPI(
    title="Urban Edge Vision Analytics",
    description="Operational observability API for edge vision inference at smart intersections",
    version="0.1.0",
    lifespan=lifespan,
)


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
def list_events(camera_id: str | None = None) -> list[TrafficEvent]:
    return _store.list_events(camera_id=camera_id)


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
def list_incidents(status: IncidentStatus | None = None) -> list[IntersectionIncident]:
    return _store.list_incidents(status=status)


class UpdateIncidentRequest(BaseModel):
    status: IncidentStatus
    notes: str = ""


@app.patch("/incidents/{incident_id}")
def update_incident(incident_id: str, req: UpdateIncidentRequest) -> IntersectionIncident:
    incident = _store.update_incident_status(
        incident_id=incident_id,
        status=req.status,
        notes=req.notes,
    )
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident
