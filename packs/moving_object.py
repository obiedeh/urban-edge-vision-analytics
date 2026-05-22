from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from analytics.flow import FlowWindow
from events.schemas import Direction, EventType, MovingObjectEvent, Severity
from vision.schemas import VehicleClass, VehicleDetection

from .base import PackId, ReportWindow


class MovingObjectConfig(BaseModel):
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    target_classes: list[str] = Field(default_factory=lambda: ["pedestrian"])


class MovingObjectPack:
    pack_id = PackId.moving_object
    version = "1.0.0"
    parameters = MovingObjectConfig
    requires: set[str] = set()

    def evaluate(
        self,
        detections: list[VehicleDetection],
        flow: FlowWindow,
        config: BaseModel,
        window: ReportWindow,
    ) -> Iterable[MovingObjectEvent]:
        cfg = config if isinstance(config, MovingObjectConfig) else MovingObjectConfig()
        persons = [
            d
            for d in detections
            if d.vehicle_class == VehicleClass.pedestrian
            and d.bounding_box.confidence >= cfg.confidence_threshold
        ]
        now = datetime.now(UTC)
        for person in persons:
            yield MovingObjectEvent(
                event_id=str(uuid.uuid4()),
                camera_id=window.camera_id,
                event_type=EventType.person_activity,
                severity=Severity.info,
                timestamp=now,
                track_id=person.track_id,
                person_descriptor=_heuristic_descriptor(person),
                attributes=_heuristic_attributes(person),
                direction=Direction(),
                detected_at=now,
                last_seen_at=now,
            )


def _heuristic_descriptor(d: VehicleDetection) -> str:
    w = d.bounding_box.width
    size = "large" if w > 100 else "medium" if w > 50 else "small"
    return f"{size} person"


def _heuristic_attributes(d: VehicleDetection) -> dict:
    return {
        "size_estimate": "medium",
        "color_top": "unknown",
        "color_bottom": "unknown",
    }
