import json
from datetime import UTC, datetime

import pytest

from cloud import CloudEnvelope, EventPublisher, FilePublisher, NullPublisher, build_publisher
from events.schemas import (
    Direction,
    EventType,
    IntersectionIncident,
    MovingObjectEvent,
    Severity,
    SpeedViolationEvent,
    StopSignEvent,
    TrafficEvent,
    VehicleType,
)
from telemetry.metrics import InferenceMetrics
from telemetry.runtime import RuntimeSnapshot
from telemetry.schemas import EdgeTelemetry, InferenceMetricsSnapshot, RuntimeTelemetry
from vision.schemas import BoundingBox, InferenceFrame, VehicleClass, VehicleDetection

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def _event() -> TrafficEvent:
    return TrafficEvent(
        event_id="e1",
        camera_id="cam-1",
        event_type=EventType.red_light_violation,
        severity=Severity.critical,
        timestamp=NOW,
        vehicle_count=2,
        track_ids=["t1", "t2"],
        confidence=0.9,
        operator_review_recommended=True,
        vlm_summary="ran the light",
        metadata={"lane": 3, "nested": {"ok": True}},
    )


def _incident() -> IntersectionIncident:
    return IntersectionIncident(
        incident_id="i1",
        camera_id="cam-1",
        event_ids=["e1"],
        severity=Severity.critical,
        summary="Red light",
        created_at=NOW,
        updated_at=NOW,
    )


def _telemetry() -> EdgeTelemetry:
    metrics = InferenceMetrics(frames_dropped=1)
    metrics.record(12.5)
    return EdgeTelemetry.from_dataclasses(RuntimeSnapshot(camera_count=1, event_count=4), metrics)


def _detection() -> VehicleDetection:
    return VehicleDetection(
        track_id="t1",
        vehicle_class=VehicleClass.truck,
        bounding_box=BoundingBox(x=1, y=2, width=3, height=4, confidence=0.5),
        frame_id="f1",
        timestamp_ms=123,
    )


def _frame() -> InferenceFrame:
    return InferenceFrame(
        frame_id="f1",
        camera_id="cam-1",
        timestamp_ms=123,
        width=640,
        height=480,
        detections=[_detection()],
        inference_latency_ms=9.5,
    )


def _direction() -> Direction:
    return Direction(compass="NE", heading_deg=45.0, velocity_px_per_s=3.2)


CONTRACT_MODELS = [
    _event(),
    _incident(),
    _telemetry(),
    _detection(),
    _frame(),
    RuntimeTelemetry.from_dataclass(RuntimeSnapshot()),
    InferenceMetricsSnapshot.from_dataclass(InferenceMetrics()),
    MovingObjectEvent(
        event_id="e2",
        camera_id="cam-1",
        severity=Severity.info,
        timestamp=NOW,
        person_descriptor="adult, red jacket",
        attributes={"color_top": "red"},
        direction=_direction(),
        track_id="p1",
        detected_at=NOW,
        last_seen_at=NOW,
    ),
    SpeedViolationEvent(
        event_id="e3",
        camera_id="cam-1",
        severity=Severity.warning,
        timestamp=NOW,
        vehicle_type=VehicleType.car,
        vehicle_color="blue",
        vehicle_descriptor="blue sedan",
        measured_speed=41.0,
        unit="mph",
        posted_speed=25.0,
        exceedance=16.0,
        direction=_direction(),
        track_id="v1",
        detected_at=NOW,
    ),
    StopSignEvent(
        event_id="e4",
        camera_id="cam-1",
        severity=Severity.warning,
        timestamp=NOW,
        decision="rolling_stop",
        min_speed_in_zone=4.0,
        dwell_ms=300,
        vehicle_type=VehicleType.van,
        vehicle_color="white",
        vehicle_descriptor="white van",
        direction=_direction(),
        track_id="v2",
        detected_at=NOW,
    ),
]


@pytest.mark.parametrize("model", CONTRACT_MODELS, ids=lambda m: type(m).__name__)
def test_every_schema_roundtrips_through_envelope(model):
    envelope = CloudEnvelope.wrap("event", model, thing_name="thing-a", schema_version=1)
    wire = envelope.model_dump_json()
    parsed = CloudEnvelope.model_validate_json(wire)
    assert parsed == envelope
    assert parsed.payload["schema_version"] == 1
    assert type(model).model_validate(parsed.payload) == model


def test_envelope_fields_and_utc_sent_at():
    env = CloudEnvelope.wrap("incident", _incident(), thing_name="thing-a", schema_version=1)
    assert env.kind == "incident"
    assert env.thing_name == "thing-a"
    assert env.sent_at.tzinfo is not None and env.sent_at.utcoffset().total_seconds() == 0
    data = json.loads(env.model_dump_json())
    assert set(data) == {"schema_version", "thing_name", "sent_at", "kind", "payload"}
    assert data["payload"] == _incident().model_dump(mode="json")
    assert data["payload"]["created_at"].endswith("Z") or "+00:00" in data["payload"]["created_at"]


def test_envelope_rejects_unknown_kind():
    with pytest.raises(ValueError):
        CloudEnvelope.wrap("video", _event(), thing_name="t", schema_version=1)  # type: ignore[arg-type]


def test_frame_bytes_never_leak_into_envelope():
    frame = _frame().model_copy(update={"frame_bytes": b"\x00\x01"})
    env = CloudEnvelope.wrap("event", frame, thing_name="t", schema_version=1)
    assert "frame_bytes" not in env.payload


def test_null_publisher_is_a_noop(tmp_path):
    with NullPublisher() as pub:
        pub.publish_event(_event())
        pub.publish_incident(_incident())
        pub.publish_telemetry(_telemetry())
        pub.flush()
    pub.close()  # idempotent
    assert list(tmp_path.iterdir()) == []


def test_file_publisher_writes_valid_jsonl(tmp_path):
    out = tmp_path / "nested" / "cloud.jsonl"
    with FilePublisher(out, thing_name="thing-b", schema_version=1) as pub:
        pub.publish_event(_event())
        pub.publish_telemetry(_telemetry())
        pub.publish_incident(_incident())
        pub.flush()
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    envelopes = [CloudEnvelope.model_validate_json(line) for line in lines]
    assert [e.kind for e in envelopes] == ["event", "telemetry", "incident"]
    assert all(e.thing_name == "thing-b" for e in envelopes)
    assert TrafficEvent.model_validate(envelopes[0].payload) == _event()
    assert EdgeTelemetry.model_validate(envelopes[1].payload) == _telemetry()
    assert IntersectionIncident.model_validate(envelopes[2].payload) == _incident()


def test_file_publisher_appends_across_instances(tmp_path):
    out = tmp_path / "cloud.jsonl"
    with FilePublisher(out, thing_name="t") as pub:
        pub.publish_event(_event())
    with FilePublisher(out, thing_name="t") as pub:
        pub.publish_event(_event())
    assert len(out.read_text().splitlines()) == 2


def test_file_publisher_close_without_publish_is_safe(tmp_path):
    pub = FilePublisher(tmp_path / "never.jsonl", thing_name="t")
    pub.flush()
    pub.close()
    assert not (tmp_path / "never.jsonl").exists()


def test_publish_failure_is_logged_not_raised(caplog):
    class Broken(EventPublisher):
        def _publish(self, envelope):
            raise OSError("disk full")

        def flush(self):
            return None

        def close(self):
            return None

    pub = Broken(thing_name="t")
    with caplog.at_level("ERROR", logger="cloud.publisher"):
        pub.publish_event(_event())  # must not raise
    assert "Dropped event message" in caplog.text


def test_build_publisher_disabled_returns_null():
    pub = build_publisher(enabled=False, publisher="file", thing_name="t", file_path="/x")
    assert isinstance(pub, NullPublisher)
    pub = build_publisher(enabled=True, publisher="null", thing_name="t")
    assert isinstance(pub, NullPublisher)


def test_build_publisher_file(tmp_path):
    pub = build_publisher(
        enabled=True, publisher="file", thing_name="t", file_path=str(tmp_path / "o.jsonl")
    )
    assert isinstance(pub, FilePublisher)
    with pytest.raises(ValueError):
        build_publisher(enabled=True, publisher="file", thing_name="t")
    with pytest.raises(ValueError):
        build_publisher(enabled=True, publisher="mqtt", thing_name="t")
