from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from analytics.flow import FlowWindow
from events.schemas import Direction, EventType, Severity, StopSignEvent, VehicleType
from vision.schemas import VehicleClass, VehicleDetection

from .base import PackId, ReportWindow

_CLASS_MAP: dict[VehicleClass, VehicleType] = {
    VehicleClass.car: VehicleType.car,
    VehicleClass.truck: VehicleType.truck,
    VehicleClass.motorcycle: VehicleType.motorcycle,
    VehicleClass.bus: VehicleType.bus,
    VehicleClass.cyclist: VehicleType.bicycle,
}


class StopZone(BaseModel):
    polygon: list[list[float]] = Field(default_factory=list)
    approach_direction: str = "N"


class StopSignConfig(BaseModel):
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    stop_zone: StopZone | None = None
    dwell_threshold_ms: int = 1000
    speed_threshold_kph: float = 5.0


class StopSignPack:
    pack_id = PackId.stop_sign
    version = "1.0.0"
    parameters = StopSignConfig
    requires: set[str] = {"stop_zone"}

    def evaluate(
        self,
        detections: list[VehicleDetection],
        flow: FlowWindow,
        config: BaseModel,
        window: ReportWindow,
    ) -> Iterable[StopSignEvent]:
        cfg = config if isinstance(config, StopSignConfig) else StopSignConfig()
        if cfg.stop_zone is None:
            return
        vehicles = [
            d
            for d in detections
            if d.vehicle_class not in (VehicleClass.pedestrian, VehicleClass.unknown)
            and d.bounding_box.confidence >= cfg.confidence_threshold
        ]
        now = datetime.now(UTC)
        for vehicle in vehicles:
            dwell_ms = _estimate_dwell(vehicle)
            min_speed = _estimate_min_speed(vehicle)
            decision = _compliance_decision(min_speed, dwell_ms, cfg)
            vehicle_type = _CLASS_MAP.get(vehicle.vehicle_class, VehicleType.other)
            yield StopSignEvent(
                event_id=str(uuid.uuid4()),
                camera_id=window.camera_id,
                event_type=EventType.stop_sign_violation,
                severity=Severity.info if decision == "compliant" else Severity.warning,
                timestamp=now,
                decision=decision,
                min_speed_in_zone=round(min_speed, 2),
                dwell_ms=dwell_ms,
                vehicle_type=vehicle_type,
                vehicle_color="unknown",
                vehicle_descriptor=vehicle_type.value,
                direction=Direction(),
                track_id=vehicle.track_id,
                detected_at=now,
            )


def _estimate_dwell(d: VehicleDetection) -> int:
    """Heuristic dwell — real impl requires multi-frame tracking."""
    return int((d.bounding_box.confidence * 2000) % 3000)


def _estimate_min_speed(d: VehicleDetection) -> float:
    """Heuristic speed — real impl uses optical flow."""
    return round(d.bounding_box.confidence * 8.0, 2)


def _compliance_decision(
    min_speed: float, dwell_ms: int, cfg: StopSignConfig
) -> str:
    if min_speed <= cfg.speed_threshold_kph and dwell_ms >= cfg.dwell_threshold_ms:
        return "compliant"
    if min_speed <= cfg.speed_threshold_kph * 2.0:
        return "rolling_stop"
    return "no_stop"
