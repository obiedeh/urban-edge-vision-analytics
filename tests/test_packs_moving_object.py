from __future__ import annotations

import time

import pytest

from analytics.flow import FlowWindow
from events.schemas import EventType
from packs.base import PackId, ReportWindow
from packs.moving_object import MovingObjectConfig, MovingObjectPack
from vision.schemas import BoundingBox, InferenceFrame, VehicleClass, VehicleDetection


def _frame(camera_id: str = "cam-1") -> InferenceFrame:
    return InferenceFrame(
        frame_id="f1",
        camera_id=camera_id,
        timestamp_ms=0,
        width=1920,
        height=1080,
    )


def _detection(
    track_id: str = "t1",
    vehicle_class: VehicleClass = VehicleClass.pedestrian,
    confidence: float = 0.9,
    width: float = 60.0,
) -> VehicleDetection:
    return VehicleDetection(
        track_id=track_id,
        vehicle_class=vehicle_class,
        bounding_box=BoundingBox(x=100, y=100, width=width, height=80, confidence=confidence),
        frame_id="f1",
        timestamp_ms=0,
    )


def _window(camera_id: str = "cam-1", interval: int = 5) -> ReportWindow:
    return ReportWindow(
        camera_id=camera_id, report_interval_seconds=interval, now_ts=time.time()
    )


@pytest.fixture
def pack() -> MovingObjectPack:
    return MovingObjectPack()


@pytest.fixture
def flow() -> FlowWindow:
    return FlowWindow(camera_id="cam-1")


def test_pack_id(pack: MovingObjectPack) -> None:
    assert pack.pack_id == PackId.moving_object


def test_no_requires(pack: MovingObjectPack) -> None:
    assert pack.requires == set()


def test_emits_for_pedestrian(pack: MovingObjectPack, flow: FlowWindow) -> None:
    detections = [_detection(vehicle_class=VehicleClass.pedestrian)]
    events = list(pack.evaluate(detections, flow, MovingObjectConfig(), _window()))
    assert len(events) == 1
    assert events[0].event_type == EventType.person_activity
    assert events[0].track_id == "t1"


def test_skips_non_pedestrian(pack: MovingObjectPack, flow: FlowWindow) -> None:
    detections = [_detection(vehicle_class=VehicleClass.car)]
    events = list(pack.evaluate(detections, flow, MovingObjectConfig(), _window()))
    assert events == []


def test_skips_low_confidence(pack: MovingObjectPack, flow: FlowWindow) -> None:
    detections = [_detection(vehicle_class=VehicleClass.pedestrian, confidence=0.3)]
    cfg = MovingObjectConfig(confidence_threshold=0.5)
    events = list(pack.evaluate(detections, flow, cfg, _window()))
    assert events == []


def test_multiple_persons(pack: MovingObjectPack, flow: FlowWindow) -> None:
    detections = [
        _detection(track_id="t1", vehicle_class=VehicleClass.pedestrian),
        _detection(track_id="t2", vehicle_class=VehicleClass.pedestrian),
    ]
    events = list(pack.evaluate(detections, flow, MovingObjectConfig(), _window()))
    assert len(events) == 2


def test_person_descriptor_size(pack: MovingObjectPack, flow: FlowWindow) -> None:
    small = _detection(vehicle_class=VehicleClass.pedestrian, width=30)
    medium = _detection(vehicle_class=VehicleClass.pedestrian, width=70)
    large = _detection(vehicle_class=VehicleClass.pedestrian, width=120)
    for det, expected in [(small, "small"), (medium, "medium"), (large, "large")]:
        events = list(pack.evaluate([det], flow, MovingObjectConfig(), _window()))
        assert expected in events[0].person_descriptor


def test_attributes_keys(pack: MovingObjectPack, flow: FlowWindow) -> None:
    detections = [_detection(vehicle_class=VehicleClass.pedestrian)]
    events = list(pack.evaluate(detections, flow, MovingObjectConfig(), _window()))
    attrs = events[0].attributes
    assert "size_estimate" in attrs
    assert "color_top" in attrs
    assert "color_bottom" in attrs
