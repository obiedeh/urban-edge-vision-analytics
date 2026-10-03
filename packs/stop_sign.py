"""Stop-sign compliance from tracked vehicles and an operator-drawn stop zone.

A vehicle track that enters the zone polygon is watched until it leaves (or
the track is lost). The decision uses what the frames actually show:

* ``dwell_ms`` — wall-clock time the ground point stayed inside the zone;
* ``min_speed_in_zone`` — minimum tracked speed inside the zone, in
  frame-widths per second (no real-world calibration is claimed).

Thresholds are pack parameters; the defaults suit a 1 Hz inference cadence.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from analytics.flow import FlowWindow
from events.schemas import Direction, EventType, Severity, StopSignEvent, VehicleType
from packs.geometry import bottom_center, compass_from_vector, point_in_polygon
from vision.schemas import VehicleClass, VehicleDetection

from .base import PackId, ReportWindow

_CLASS_MAP: dict[VehicleClass, VehicleType] = {
    VehicleClass.car: VehicleType.car,
    VehicleClass.truck: VehicleType.truck,
    VehicleClass.motorcycle: VehicleType.motorcycle,
    VehicleClass.bus: VehicleType.bus,
    VehicleClass.cyclist: VehicleType.bicycle,
}

Decision = Literal["compliant", "rolling_stop", "no_stop"]


class StopZone(BaseModel):
    polygon: list[list[float]] = Field(default_factory=list)  # normalised 0..1
    approach_direction: str = "N"


class StopSignConfig(BaseModel):
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    stop_zone: StopZone | None = None
    dwell_threshold_ms: int = 1000
    # Speed in frame-widths per second that still counts as "stopped".
    stop_speed_threshold: float = Field(default=0.02, ge=0.0)
    # Above this (and never below stop threshold) the vehicle did not stop at all.
    rolling_speed_threshold: float = Field(default=0.08, ge=0.0)
    # Emit a compliant event too (default: only violations reach the queue).
    report_compliant: bool = True


@dataclass
class _ZoneVisit:
    entered_ts: float
    last_inside_ts: float
    min_speed: float
    vehicle_class: VehicleClass
    last_vx: float
    last_vy: float


class StopSignPack:
    pack_id = PackId.stop_sign
    version = "2.0.0"
    parameters = StopSignConfig
    requires: set[str] = {"stop_zone"}

    def __init__(self) -> None:
        self._visits: dict[str, _ZoneVisit] = {}

    def reset(self) -> None:
        self._visits.clear()

    def evaluate(
        self,
        detections: list[VehicleDetection],
        flow: FlowWindow,
        config: BaseModel,
        window: ReportWindow,
    ) -> Iterable[StopSignEvent]:
        cfg = config if isinstance(config, StopSignConfig) else StopSignConfig()
        if cfg.stop_zone is None or len(cfg.stop_zone.polygon) < 3:
            return
        polygon = cfg.stop_zone.polygon
        now_ts = window.now_ts
        seen: set[str] = set()
        for det in detections:
            if det.vehicle_class in (VehicleClass.pedestrian, VehicleClass.unknown):
                continue
            if det.bounding_box.confidence < cfg.confidence_threshold:
                continue
            bb = det.bounding_box
            inside = point_in_polygon(bottom_center(bb.x, bb.y, bb.width, bb.height), polygon)
            track = det.metadata.get("track", {}) if isinstance(det.metadata, dict) else {}
            speed = float(track.get("speed", 0.0))
            visit = self._visits.get(det.track_id)
            if inside:
                seen.add(det.track_id)
                if visit is None:
                    self._visits[det.track_id] = _ZoneVisit(
                        entered_ts=now_ts, last_inside_ts=now_ts, min_speed=speed,
                        vehicle_class=det.vehicle_class,
                        last_vx=float(track.get("vx", 0.0)), last_vy=float(track.get("vy", 0.0)),
                    )
                else:
                    visit.last_inside_ts = now_ts
                    visit.min_speed = min(visit.min_speed, speed)
                    visit.vehicle_class = det.vehicle_class
                    visit.last_vx = float(track.get("vx", 0.0))
                    visit.last_vy = float(track.get("vy", 0.0))
            elif visit is not None:
                # Left the zone: finalise.
                yield from self._finalise(det.track_id, visit, cfg, window)
        # Tracks that vanished while inside the zone are finalised by on_track_lost.

    def on_track_lost(
        self, track_id: str, config: BaseModel, window: ReportWindow
    ) -> Iterable[StopSignEvent]:
        visit = self._visits.get(track_id)
        if visit is None:
            return
        cfg = config if isinstance(config, StopSignConfig) else StopSignConfig()
        yield from self._finalise(track_id, visit, cfg, window)

    def _finalise(
        self, track_id: str, visit: _ZoneVisit, cfg: StopSignConfig, window: ReportWindow
    ) -> Iterable[StopSignEvent]:
        self._visits.pop(track_id, None)
        dwell_ms = int(max(0.0, visit.last_inside_ts - visit.entered_ts) * 1000)
        decision = _compliance_decision(visit.min_speed, dwell_ms, cfg)
        if decision == "compliant" and not cfg.report_compliant:
            return
        vehicle_type = _CLASS_MAP.get(visit.vehicle_class, VehicleType.other)
        now = datetime.now(UTC)
        yield StopSignEvent(
            event_id=str(uuid.uuid4()),
            camera_id=window.camera_id,
            event_type=EventType.stop_sign_violation,
            severity=Severity.info if decision == "compliant" else Severity.warning,
            operator_review_recommended=decision != "compliant",
            timestamp=now,
            decision=decision,
            min_speed_in_zone=round(visit.min_speed, 4),
            dwell_ms=dwell_ms,
            vehicle_type=vehicle_type,
            vehicle_color="unknown",
            vehicle_descriptor=vehicle_type.value,
            direction=Direction(
                compass=compass_from_vector(visit.last_vx, visit.last_vy),
                velocity_px_per_s=None,
            ),
            track_id=track_id,
            detected_at=datetime.fromtimestamp(visit.entered_ts, tz=UTC),
            metadata={
                "speed_unit": "frame_widths_per_second",
                "zone_entered_at": datetime.fromtimestamp(visit.entered_ts, tz=UTC).isoformat(),
            },
        )


def _compliance_decision(min_speed: float, dwell_ms: int, cfg: StopSignConfig) -> Decision:
    if min_speed <= cfg.stop_speed_threshold and dwell_ms >= cfg.dwell_threshold_ms:
        return "compliant"
    if min_speed <= cfg.rolling_speed_threshold:
        return "rolling_stop"
    return "no_stop"
