from __future__ import annotations
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class EventType(str, Enum):
    vehicle_detected = "vehicle_detected"
    red_light_violation = "red_light_violation"
    unsafe_turn = "unsafe_turn"
    congestion_onset = "congestion_onset"
    congestion_clear = "congestion_clear"
    wrong_way = "wrong_way"


class Severity(str, Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class TrafficEvent(BaseModel):
    event_id: str
    camera_id: str
    event_type: EventType
    severity: Severity
    timestamp: datetime
    vehicle_count: int = 0
    track_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    operator_review_recommended: bool = False
    metadata: dict = Field(default_factory=dict)


class IncidentStatus(str, Enum):
    open = "open"
    under_review = "under_review"
    resolved = "resolved"
    dismissed = "dismissed"


class IntersectionIncident(BaseModel):
    incident_id: str
    camera_id: str
    event_ids: list[str]
    status: IncidentStatus = IncidentStatus.open
    summary: str = ""
    created_at: datetime
    updated_at: datetime
    severity: Severity
    operator_notes: str = ""
