from __future__ import annotations

import time

import pytest

from analytics.flow import FlowWindow
from events.schemas import EventType
from packs.base import PackId, ReportWindow
from packs.stop_sign import StopSignConfig, StopSignPack, StopZone
from vision.schemas import BoundingBox, VehicleClass, VehicleDetection


def _detection(
    track_id: str = "t1",
    vehicle_class: VehicleClass = VehicleClass.car,
    confidence: float = 0.9,
) -> VehicleDetection:
    return VehicleDetection(
        track_id=track_id,
        vehicle_class=vehicle_class,
        bounding_box=BoundingBox(x=100, y=100, width=80, height=60, confidence=confidence),
        frame_id="f1",
        timestamp_ms=0,
    )


def _zone() -> StopZone:
    return StopZone(polygon=[[0, 0], [100, 0], [100, 100], [0, 100]])


def _config(zone: StopZone | None = None, dwell_ms: int = 1000) -> StopSignConfig:
    return StopSignConfig(
        stop_zone=zone or _zone(),
        dwell_threshold_ms=dwell_ms,
        speed_threshold_kph=5.0,
    )


def _window(camera_id: str = "cam-1") -> ReportWindow:
    return ReportWindow(camera_id=camera_id, report_interval_seconds=5, now_ts=time.time())


@pytest.fixture
def pack() -> StopSignPack:
    return StopSignPack()


@pytest.fixture
def flow() -> FlowWindow:
    return FlowWindow(camera_id="cam-1")


def test_pack_id(pack: StopSignPack) -> None:
    assert pack.pack_id == PackId.stop_sign


def test_requires_stop_zone(pack: StopSignPack) -> None:
    assert "stop_zone" in pack.requires


def test_no_events_without_stop_zone(pack: StopSignPack, flow: FlowWindow) -> None:
    cfg = StopSignConfig(stop_zone=None)
    events = list(pack.evaluate([_detection()], flow, cfg, _window()))
    assert events == []


def test_emits_event_for_vehicle(pack: StopSignPack, flow: FlowWindow) -> None:
    events = list(pack.evaluate([_detection()], flow, _config(), _window()))
    assert len(events) == 1
    assert events[0].event_type == EventType.stop_sign_violation


def test_skips_pedestrian(pack: StopSignPack, flow: FlowWindow) -> None:
    det = _detection(vehicle_class=VehicleClass.pedestrian)
    events = list(pack.evaluate([det], flow, _config(), _window()))
    assert events == []


def test_skips_low_confidence(pack: StopSignPack, flow: FlowWindow) -> None:
    det = _detection(confidence=0.2)
    cfg = StopSignConfig(stop_zone=_zone(), confidence_threshold=0.5)
    events = list(pack.evaluate([det], flow, cfg, _window()))
    assert events == []


def test_decision_values(pack: StopSignPack, flow: FlowWindow) -> None:
    events = list(pack.evaluate([_detection()], flow, _config(), _window()))
    assert events[0].decision in {"compliant", "rolling_stop", "no_stop"}


def test_multiple_vehicles(pack: StopSignPack, flow: FlowWindow) -> None:
    detections = [_detection("t1"), _detection("t2"), _detection("t3")]
    events = list(pack.evaluate(detections, flow, _config(), _window()))
    assert len(events) == 3


def test_dwell_ms_non_negative(pack: StopSignPack, flow: FlowWindow) -> None:
    events = list(pack.evaluate([_detection()], flow, _config(), _window()))
    assert events[0].dwell_ms >= 0


def test_min_speed_non_negative(pack: StopSignPack, flow: FlowWindow) -> None:
    events = list(pack.evaluate([_detection()], flow, _config(), _window()))
    assert events[0].min_speed_in_zone >= 0.0
