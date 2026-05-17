import uuid

import pytest

from analytics.flow import FlowWindow
from vision.schemas import BoundingBox, InferenceFrame, VehicleClass, VehicleDetection


def _make_frame(n_vehicles: int, camera_id: str = "cam-001") -> InferenceFrame:
    detections = [
        VehicleDetection(
            track_id=str(uuid.uuid4())[:8],
            vehicle_class=VehicleClass.car,
            bounding_box=BoundingBox(x=0, y=0, width=50, height=40, confidence=0.9),
            frame_id=str(uuid.uuid4()),
            timestamp_ms=1000,
        )
        for _ in range(n_vehicles)
    ]
    return InferenceFrame(
        frame_id=str(uuid.uuid4()),
        camera_id=camera_id,
        timestamp_ms=1000,
        width=1920,
        height=1080,
        detections=detections,
        inference_latency_ms=5.0,
    )


def test_vehicle_count():
    window = FlowWindow(camera_id="cam-001")
    window.push(_make_frame(3))
    assert window.vehicle_count == 3


def test_congestion_triggered():
    window = FlowWindow(camera_id="cam-001", congestion_threshold=5)
    window.push(_make_frame(6))
    assert window.is_congested is True


def test_no_congestion():
    window = FlowWindow(camera_id="cam-001", congestion_threshold=10)
    window.push(_make_frame(2))
    assert window.is_congested is False


def test_mean_latency():
    window = FlowWindow(camera_id="cam-001")
    window.push(_make_frame(1))
    assert window.mean_inference_latency_ms == 5.0


def test_empty_window_count():
    window = FlowWindow(camera_id="cam-001")
    assert window.vehicle_count == 0
    assert window.is_congested is False
    assert window.mean_inference_latency_ms is None


def test_window_size_cap():
    window = FlowWindow(camera_id="cam-001", window_size=3)
    for _ in range(10):
        window.push(_make_frame(1))
    assert len(window._frames) == 3


def test_class_counts():
    window = FlowWindow(camera_id="cam-001")
    window.push(_make_frame(3))
    counts = window.class_counts()
    assert counts.get("car", 0) == 3
