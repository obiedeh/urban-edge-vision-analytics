import uuid
from datetime import UTC, datetime

from events.schemas import EventType, Severity, TrafficEvent
from vision.schemas import BoundingBox, InferenceFrame, VehicleClass, VehicleDetection
from vision.source_loader import synthetic_frames


def test_bounding_box_confidence_bounds():
    bb = BoundingBox(x=0, y=0, width=100, height=50, confidence=0.85)
    assert bb.confidence == 0.85


def test_vehicle_detection_roundtrip():
    det = VehicleDetection(
        track_id="abc123",
        vehicle_class=VehicleClass.car,
        bounding_box=BoundingBox(x=10, y=20, width=80, height=60, confidence=0.9),
        frame_id="frame-001",
        timestamp_ms=1000,
    )
    assert det.model_dump()["vehicle_class"] == "car"


def test_inference_frame_empty_detections():
    frame = InferenceFrame(
        frame_id=str(uuid.uuid4()),
        camera_id="cam-001",
        timestamp_ms=1000,
        width=1920,
        height=1080,
    )
    assert frame.detections == []
    assert frame.inference_latency_ms is None


def test_traffic_event_defaults():
    event = TrafficEvent(
        event_id=str(uuid.uuid4()),
        camera_id="cam-001",
        event_type=EventType.vehicle_detected,
        severity=Severity.info,
        timestamp=datetime.now(UTC),
    )
    assert event.operator_review_recommended is False
    assert event.track_ids == []
    assert event.vehicle_count == 0


def test_synthetic_frames_yields_correct_count():
    frames = list(synthetic_frames(camera_id="cam-test", count=5))
    assert len(frames) == 5
    assert all(f.camera_id == "cam-test" for f in frames)
    assert all(f.source_type == "synthetic" for f in frames)


def test_synthetic_frames_timestamps_are_monotonic():
    frames = list(synthetic_frames(fps=10.0, count=4))
    timestamps = [f.timestamp_ms for f in frames]
    assert timestamps == sorted(timestamps)
    assert timestamps[1] - timestamps[0] == 100  # 1000ms / 10fps


def test_synthetic_frames_unlimited_yields_lazily():
    gen = synthetic_frames()
    first = next(gen)
    second = next(gen)
    assert first.frame_id != second.frame_id
