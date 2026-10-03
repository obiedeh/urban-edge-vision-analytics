from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class EventType(StrEnum):
    vehicle_detected = "vehicle_detected"
    scene_clear = "scene_clear"          # no moving objects in frame
    red_light_violation = "red_light_violation"
    unsafe_turn = "unsafe_turn"
    congestion_onset = "congestion_onset"
    congestion_clear = "congestion_clear"
    wrong_way = "wrong_way"
    # new — use case packs
    person_activity = "person_activity"
    speed_violation = "speed_violation"
    stop_sign_violation = "stop_sign_violation"
    vehicle_count = "vehicle_count"


class Severity(StrEnum):
    info = "info"
    warning = "warning"
    critical = "critical"


class VehicleType(StrEnum):
    car = "car"
    truck = "truck"
    motorcycle = "motorcycle"
    bus = "bus"
    van = "van"
    bicycle = "bicycle"
    other = "other"


class Direction(BaseModel):
    compass: Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"] | None = None
    heading_deg: float | None = None
    velocity_px_per_s: float | None = None


class TrafficEvent(BaseModel):
    schema_version: Literal[1] = 1
    event_id: str
    camera_id: str
    event_type: EventType
    severity: Severity
    timestamp: datetime
    vehicle_count: int = 0
    track_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    operator_review_recommended: bool = False
    vlm_summary: str | None = None
    vlm_reasoning: str | None = None
    vlm_model: str | None = None
    metadata: dict = Field(default_factory=dict)


# ── Pack 1 — Moving Object Detection ─────────────────────────────────────────


class MovingObjectEvent(TrafficEvent):
    event_type: Literal[EventType.person_activity] = EventType.person_activity
    target_kind: Literal["person"] = "person"
    person_descriptor: str
    attributes: dict  # color_top, color_bottom, size_estimate (heuristic at MVP)
    direction: Direction
    track_id: str
    detected_at: datetime
    last_seen_at: datetime


# ── Pack 2 — Speed Violation ──────────────────────────────────────────────────


class SpeedViolationEvent(TrafficEvent):
    event_type: Literal[EventType.speed_violation] = EventType.speed_violation
    target_kind: Literal["vehicle"] = "vehicle"
    vehicle_type: VehicleType
    vehicle_brand: str | None = None  # null at MVP
    vehicle_color: str
    vehicle_descriptor: str
    measured_speed: float
    unit: Literal["mph", "kph"]
    posted_speed: float
    exceedance: float
    direction: Direction
    track_id: str
    detected_at: datetime


# ── Pack 3 — Stop Sign Compliance ────────────────────────────────────────────


class StopSignEvent(TrafficEvent):
    event_type: Literal[EventType.stop_sign_violation] = EventType.stop_sign_violation
    target_kind: Literal["vehicle"] = "vehicle"
    decision: Literal["compliant", "rolling_stop", "no_stop"]
    min_speed_in_zone: float
    dwell_ms: int
    vehicle_type: VehicleType
    vehicle_color: str
    vehicle_descriptor: str
    direction: Direction
    track_id: str
    detected_at: datetime


# ── Pack 4 — Vehicle Count ────────────────────────────────────────────────────


class VehicleCountEvent(TrafficEvent):
    """One record per tracked vehicle crossing the count line. Not a review item."""

    event_type: Literal[EventType.vehicle_count] = EventType.vehicle_count
    target_kind: Literal["vehicle"] = "vehicle"
    vehicle_type: VehicleType
    # "a_to_b" / "b_to_a" relative to the drawn line, plus the operator's label
    # for that direction (e.g. northbound) and the compass heading of the track.
    crossing: Literal["a_to_b", "b_to_a"]
    direction_label: str
    direction: Direction
    track_id: str
    counted_at: datetime


# ── Incident management ───────────────────────────────────────────────────────


class IncidentStatus(StrEnum):
    open = "open"
    under_review = "under_review"
    resolved = "resolved"
    dismissed = "dismissed"


class IntersectionIncident(BaseModel):
    schema_version: Literal[1] = 1
    incident_id: str
    camera_id: str
    event_ids: list[str]
    status: IncidentStatus = IncidentStatus.open
    summary: str = ""
    created_at: datetime
    updated_at: datetime
    severity: Severity
    operator_notes: str = ""
