from __future__ import annotations

import time

import pytest

from analytics.flow import FlowWindow
from events.schemas import EventType
from packs.base import PackId, ReportWindow
from packs.speed_violation import (
    GateConfig,
    SpeedCalibrationConfig,
    SpeedViolationConfig,
    SpeedViolationPack,
)
from vision.schemas import BoundingBox, VehicleClass, VehicleDetection


def _detection(
    track_id: str = "t1",
    vehicle_class: VehicleClass = VehicleClass.car,
    confidence: float = 0.9,
    x: float = 50.0,
) -> VehicleDetection:
    return VehicleDetection(
        track_id=track_id,
        vehicle_class=vehicle_class,
        bounding_box=BoundingBox(x=x, y=100, width=80, height=60, confidence=confidence),
        frame_id="f1",
        timestamp_ms=0,
    )


def _calibration(posted_kph: float = 50.0) -> SpeedCalibrationConfig:
    return SpeedCalibrationConfig(
        gate_a=GateConfig(x=100, y=0, width=100, height=10),
        gate_b=GateConfig(x=100, y=200, width=100, height=10),
        real_world_distance_m=20.0,
        posted_speed_kph=posted_kph,
    )


def _window(camera_id: str = "cam-1") -> ReportWindow:
    return ReportWindow(camera_id=camera_id, report_interval_seconds=5, now_ts=time.time())


@pytest.fixture
def pack() -> SpeedViolationPack:
    return SpeedViolationPack()


@pytest.fixture
def flow() -> FlowWindow:
    return FlowWindow(camera_id="cam-1")


def test_pack_id(pack: SpeedViolationPack) -> None:
    assert pack.pack_id == PackId.speed_violation


def test_requires_speed_calibration(pack: SpeedViolationPack) -> None:
    assert "speed_calibration" in pack.requires


def test_no_events_without_calibration(pack: SpeedViolationPack, flow: FlowWindow) -> None:
    cfg = SpeedViolationConfig(calibration=None)
    events = list(pack.evaluate([_detection()], flow, cfg, _window()))
    assert events == []


def test_emits_speed_violation(pack: SpeedViolationPack, flow: FlowWindow) -> None:
    # x=99 → speed > posted (heuristic ensures overspeed)
    det = _detection(x=99.0)
    cfg = SpeedViolationConfig(calibration=_calibration(posted_kph=10.0))
    events = list(pack.evaluate([det], flow, cfg, _window()))
    assert len(events) >= 1
    assert events[0].event_type == EventType.speed_violation
    assert events[0].measured_speed > events[0].posted_speed


def test_no_violation_below_posted(pack: SpeedViolationPack, flow: FlowWindow) -> None:
    cfg = SpeedViolationConfig(calibration=_calibration(posted_kph=999.0))
    events = list(pack.evaluate([_detection()], flow, cfg, _window()))
    assert events == []


def test_skips_pedestrian(pack: SpeedViolationPack, flow: FlowWindow) -> None:
    det = _detection(vehicle_class=VehicleClass.pedestrian, x=99.0)
    cfg = SpeedViolationConfig(calibration=_calibration(posted_kph=1.0))
    events = list(pack.evaluate([det], flow, cfg, _window()))
    assert events == []


def test_skips_low_confidence(pack: SpeedViolationPack, flow: FlowWindow) -> None:
    det = _detection(confidence=0.2, x=99.0)
    cfg = SpeedViolationConfig(
        calibration=_calibration(posted_kph=1.0),
        confidence_threshold=0.5,
    )
    events = list(pack.evaluate([det], flow, cfg, _window()))
    assert events == []


def test_violation_has_exceedance(pack: SpeedViolationPack, flow: FlowWindow) -> None:
    cfg = SpeedViolationConfig(calibration=_calibration(posted_kph=10.0))
    events = list(pack.evaluate([_detection(x=99.0)], flow, cfg, _window()))
    if events:
        assert events[0].exceedance == round(events[0].measured_speed - events[0].posted_speed, 1)


def test_vehicle_brand_is_none(pack: SpeedViolationPack, flow: FlowWindow) -> None:
    cfg = SpeedViolationConfig(calibration=_calibration(posted_kph=1.0))
    events = list(pack.evaluate([_detection(x=99.0)], flow, cfg, _window()))
    if events:
        assert events[0].vehicle_brand is None
