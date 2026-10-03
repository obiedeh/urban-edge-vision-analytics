"""Moving-object (person activity) pack.

Reports people (and optionally other classes) that are tracked across frames,
with direction from the track's motion. Debouncing per track is handled by
``EventReporter`` using the binding's report interval; an optional zone limits
reports to a region of interest.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from analytics.flow import FlowWindow
from events.schemas import Direction, EventType, MovingObjectEvent, Severity
from packs.geometry import bottom_center, compass_from_vector, point_in_polygon
from vision.schemas import VehicleDetection

from .base import PackId, ReportWindow


class MovingObjectConfig(BaseModel):
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    target_classes: list[str] = Field(default_factory=lambda: ["pedestrian"])
    # Minimum tracked speed (frame-widths/s) to count as "moving"; 0 reports presence.
    min_speed: float = Field(default=0.0, ge=0.0)
    zone: list[list[float]] = Field(default_factory=list)  # optional, normalised 0..1
    # Require this many observations before reporting a new track (filters flicker).
    min_observations: int = Field(default=2, ge=1)


class MovingObjectPack:
    pack_id = PackId.moving_object
    version = "2.0.0"
    parameters = MovingObjectConfig
    requires: set[str] = set()

    def __init__(self) -> None:
        self._first_seen: dict[str, float] = {}

    def reset(self) -> None:
        self._first_seen.clear()

    def evaluate(
        self,
        detections: list[VehicleDetection],
        flow: FlowWindow,
        config: BaseModel,
        window: ReportWindow,
    ) -> Iterable[MovingObjectEvent]:
        cfg = config if isinstance(config, MovingObjectConfig) else MovingObjectConfig()
        targets = {c.lower() for c in cfg.target_classes}
        now = datetime.now(UTC)
        for det in detections:
            if det.vehicle_class.value not in targets:
                continue
            if det.bounding_box.confidence < cfg.confidence_threshold:
                continue
            track = det.metadata.get("track", {}) if isinstance(det.metadata, dict) else {}
            if int(track.get("observations", 1)) < cfg.min_observations:
                continue
            speed = float(track.get("speed", 0.0))
            if speed < cfg.min_speed:
                continue
            bb = det.bounding_box
            if cfg.zone and len(cfg.zone) >= 3:
                if not point_in_polygon(bottom_center(bb.x, bb.y, bb.width, bb.height), cfg.zone):
                    continue
            first = self._first_seen.setdefault(det.track_id, window.now_ts)
            vx, vy = float(track.get("vx", 0.0)), float(track.get("vy", 0.0))
            yield MovingObjectEvent(
                event_id=str(uuid.uuid4()),
                camera_id=window.camera_id,
                event_type=EventType.person_activity,
                severity=Severity.info,
                timestamp=now,
                confidence=bb.confidence,
                track_id=det.track_id,
                target_kind="person",
                person_descriptor=_descriptor(det, speed),
                attributes={
                    "class": det.vehicle_class.value,
                    "bbox_height_frac": round(bb.height, 3),
                    "speed_frame_widths_per_s": round(speed, 4),
                },
                direction=Direction(compass=compass_from_vector(vx, vy)),
                detected_at=datetime.fromtimestamp(first, tz=UTC),
                last_seen_at=now,
            )

    def on_track_lost(
        self, track_id: str, config: BaseModel, window: ReportWindow
    ) -> Iterable[MovingObjectEvent]:
        self._first_seen.pop(track_id, None)
        return ()


def _descriptor(det: VehicleDetection, speed: float) -> str:
    height = det.bounding_box.height
    size = "near" if height > 0.4 else "mid" if height > 0.15 else "far"
    motion = "stationary" if speed < 0.01 else "walking" if speed < 0.15 else "fast-moving"
    return f"{motion} {det.vehicle_class.value} ({size})"
