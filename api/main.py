from __future__ import annotations
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from events.lifecycle import EventStore
from events.schemas import EventType, IncidentStatus, IntersectionIncident, Severity, TrafficEvent
from telemetry.metrics import InferenceMetrics
from telemetry.runtime import RuntimeSnapshot

_store = EventStore()
_inference_metrics = InferenceMetrics()
_runtime = RuntimeSnapshot()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _runtime.started_at = time.time()
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
    track_ids: list[str] = []
    confidence: float = 1.0
    operator_review_recommended: bool = False
    inference_latency_ms: float | None = None
    metadata: dict = {}


@app.post("/events", status_code=201)
def ingest_event(req: EventIngestRequest) -> TrafficEvent:
    event = TrafficEvent(
        event_id=str(uuid.uuid4()),
        camera_id=req.camera_id,
        event_type=req.event_type,
        severity=req.severity,
        timestamp=datetime.now(timezone.utc),
        vehicle_count=req.vehicle_count,
        track_ids=req.track_ids,
        confidence=req.confidence,
        operator_review_recommended=req.operator_review_recommended,
        metadata=req.metadata,
    )
    _store.add_event(event)
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
