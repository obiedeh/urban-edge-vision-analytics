"""Two-gate speed measurement from tracked vehicles.

The operator draws gate A and gate B (lines or polygons, normalised 0..1) and
enters the real-world distance between them. When a track crosses A and later
B, speed = distance / elapsed. Only measured crossings produce events; nothing
is estimated from a single frame.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from analytics.flow import FlowWindow
from events.schemas import Direction, EventType, Severity, SpeedViolationEvent, VehicleType
from packs.geometry import bottom_center, compass_from_vector, crossed_gate
from vision.schemas import VehicleClass, VehicleDetection

from .base import PackId, ReportWindow

_CLASS_MAP: dict[VehicleClass, VehicleType] = {
    VehicleClass.car: VehicleType.car,
    VehicleClass.truck: VehicleType.truck,
    VehicleClass.motorcycle: VehicleType.motorcycle,
    VehicleClass.bus: VehicleType.bus,
    VehicleClass.cyclist: VehicleType.bicycle,
}


class SpeedCalibrationConfig(BaseModel):
    gate_a: list[list[float]] = Field(default_factory=list)
    gate_b: list[list[float]] = Field(default_factory=list)
    real_world_distance_m: float = Field(default=10.0, gt=0)
    posted_speed_kph: float = Field(default=50.0, gt=0)
    unit: str = "kph"

    @field_validator("gate_a", "gate_b", mode="before")
    @classmethod
    def _coerce_gate(cls, value: Any) -> list[list[float]]:
        # Accept the legacy {x, y, width, height} rectangle as a polygon.
        if isinstance(value, dict) and {"x", "y", "width", "height"} <= set(value):
            x, y, w, h = (float(value[k]) for k in ("x", "y", "width", "height"))
            return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
        if isinstance(value, dict):
            return []
        return [[float(p[0]), float(p[1])] for p in (value or [])]


class SpeedViolationConfig(BaseModel):
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    calibration: SpeedCalibrationConfig | None = None
    # Only report crossings above the posted limit (default) or every measurement.
    report_all_measurements: bool = False
    max_transit_s: float = Field(default=30.0, gt=0)


@dataclass
class _Transit:
    crossed_a_ts: float
    vehicle_class: VehicleClass


class SpeedViolationPack:
    pack_id = PackId.speed_violation
    version = "2.0.0"
    parameters = SpeedViolationConfig
    requires: set[str] = {"speed_calibration"}

    def __init__(self) -> None:
        self._prev_point: dict[str, tuple[float, float]] = {}
        self._transits: dict[str, _Transit] = {}

    def reset(self) -> None:
        self._prev_point.clear()
        self._transits.clear()

    def evaluate(
        self,
        detections: list[VehicleDetection],
        flow: FlowWindow,
        config: BaseModel,
        window: ReportWindow,
    ) -> Iterable[SpeedViolationEvent]:
        cfg = config if isinstance(config, SpeedViolationConfig) else SpeedViolationConfig()
        cal = cfg.calibration
        if cal is None or len(cal.gate_a) < 2 or len(cal.gate_b) < 2:
            return
        now_ts = window.now_ts
        for det in detections:
            if det.vehicle_class in (VehicleClass.pedestrian, VehicleClass.unknown):
                continue
            if det.bounding_box.confidence < cfg.confidence_threshold:
                continue
            bb = det.bounding_box
            point = bottom_center(bb.x, bb.y, bb.width, bb.height)
            prev = self._prev_point.get(det.track_id)
            self._prev_point[det.track_id] = point
            if prev is None:
                continue
            transit = self._transits.get(det.track_id)
            if transit is None:
                if crossed_gate(prev, point, cal.gate_a):
                    self._transits[det.track_id] = _Transit(now_ts, det.vehicle_class)
                continue
            if now_ts - transit.crossed_a_ts > cfg.max_transit_s:
                self._transits.pop(det.track_id, None)
                continue
            if crossed_gate(prev, point, cal.gate_b):
                self._transits.pop(det.track_id, None)
                elapsed = now_ts - transit.crossed_a_ts
                if elapsed <= 0:
                    continue
                kph = cal.real_world_distance_m / elapsed * 3.6
                speed = kph if cal.unit == "kph" else kph / 1.609344
                posted = cal.posted_speed_kph
                if cal.unit != "kph":
                    posted = posted / 1.609344
                exceedance = round(speed - posted, 1)
                if exceedance <= 0 and not cfg.report_all_measurements:
                    continue
                vehicle_type = _CLASS_MAP.get(det.vehicle_class, VehicleType.other)
                track = det.metadata.get("track", {}) if isinstance(det.metadata, dict) else {}
                now = datetime.now(UTC)
                yield SpeedViolationEvent(
                    event_id=str(uuid.uuid4()),
                    camera_id=window.camera_id,
                    event_type=EventType.speed_violation,
                    severity=Severity.warning if exceedance > 0 else Severity.info,
                    operator_review_recommended=exceedance > 0,
                    timestamp=now,
                    vehicle_type=vehicle_type,
                    vehicle_brand=None,
                    vehicle_color="unknown",
                    vehicle_descriptor=vehicle_type.value,
                    measured_speed=round(speed, 1),
                    unit="kph" if cal.unit == "kph" else "mph",
                    posted_speed=round(posted, 1),
                    exceedance=exceedance,
                    direction=Direction(
                        compass=compass_from_vector(
                            float(track.get("vx", 0.0)), float(track.get("vy", 0.0))
                        )
                    ),
                    track_id=det.track_id,
                    detected_at=datetime.fromtimestamp(transit.crossed_a_ts, tz=UTC),
                    metadata={
                        "transit_s": round(elapsed, 3),
                        "distance_m": cal.real_world_distance_m,
                    },
                )

    def on_track_lost(
        self, track_id: str, config: BaseModel, window: ReportWindow
    ) -> Iterable[SpeedViolationEvent]:
        self._prev_point.pop(track_id, None)
        self._transits.pop(track_id, None)
        return ()
