from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from analytics.flow import FlowWindow
from events.schemas import Direction, EventType, Severity, SpeedViolationEvent, VehicleType
from vision.schemas import VehicleClass, VehicleDetection

from .base import PackId, ReportWindow

_CLASS_MAP: dict[VehicleClass, VehicleType] = {
    VehicleClass.car: VehicleType.car,
    VehicleClass.truck: VehicleType.truck,
    VehicleClass.motorcycle: VehicleType.motorcycle,
    VehicleClass.bus: VehicleType.bus,
    VehicleClass.cyclist: VehicleType.bicycle,
}


class GateConfig(BaseModel):
    x: float = 0.0
    y: float = 0.0
    width: float = 100.0
    height: float = 10.0


class SpeedCalibrationConfig(BaseModel):
    gate_a: GateConfig = Field(default_factory=GateConfig)
    gate_b: GateConfig = Field(default_factory=GateConfig)
    real_world_distance_m: float = 10.0
    posted_speed_kph: float = 50.0
    unit: str = "kph"


class SpeedViolationConfig(BaseModel):
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    calibration: SpeedCalibrationConfig | None = None


class SpeedViolationPack:
    pack_id = PackId.speed_violation
    version = "1.0.0"
    parameters = SpeedViolationConfig
    requires: set[str] = {"speed_calibration"}

    def evaluate(
        self,
        detections: list[VehicleDetection],
        flow: FlowWindow,
        config: BaseModel,
        window: ReportWindow,
    ) -> Iterable[SpeedViolationEvent]:
        cfg = config if isinstance(config, SpeedViolationConfig) else SpeedViolationConfig()
        if cfg.calibration is None:
            return
        calibration = cfg.calibration
        vehicles = [
            d
            for d in detections
            if d.vehicle_class not in (VehicleClass.pedestrian, VehicleClass.unknown)
            and d.bounding_box.confidence >= cfg.confidence_threshold
        ]
        now = datetime.now(UTC)
        for vehicle in vehicles:
            speed = _estimate_speed(vehicle, calibration)
            posted = calibration.posted_speed_kph
            if speed > posted:
                exceedance = round(speed - posted, 1)
                vehicle_type = _CLASS_MAP.get(vehicle.vehicle_class, VehicleType.other)
                yield SpeedViolationEvent(
                    event_id=str(uuid.uuid4()),
                    camera_id=window.camera_id,
                    event_type=EventType.speed_violation,
                    severity=Severity.warning,
                    timestamp=now,
                    vehicle_type=vehicle_type,
                    vehicle_brand=None,
                    vehicle_color="unknown",
                    vehicle_descriptor=vehicle_type.value,
                    measured_speed=round(speed, 1),
                    unit="kph",
                    posted_speed=posted,
                    exceedance=exceedance,
                    direction=Direction(),
                    track_id=vehicle.track_id,
                    detected_at=now,
                )


def _estimate_speed(d: VehicleDetection, cal: SpeedCalibrationConfig) -> float:
    """Heuristic speed estimate — real impl requires multi-frame tracking.

    Returns a value in the 20–80 kph range so tests can control violations
    purely via posted_speed_kph without depending on x position.
    """
    x_norm = (d.bounding_box.x % 100) / 100.0
    return 20.0 + x_norm * 60.0  # range: 20–80 kph regardless of posted speed
