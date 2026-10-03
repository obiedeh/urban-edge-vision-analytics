from telemetry.metrics import InferenceMetrics
from telemetry.runtime import RuntimeSnapshot
from telemetry.schemas import EdgeTelemetry, InferenceMetricsSnapshot, RuntimeTelemetry


def test_runtime_telemetry_from_dataclass_matches_to_dict():
    snap = RuntimeSnapshot(camera_count=2, event_count=5, incident_count=1)
    model = RuntimeTelemetry.from_dataclass(snap)
    assert model.schema_version == 1
    assert model.model_dump(exclude={"schema_version"}) == snap.to_dict()
    assert model.uptime_seconds == 0.0  # never started


def test_inference_metrics_snapshot_empty():
    model = InferenceMetricsSnapshot.from_dataclass(InferenceMetrics())
    assert model.sample_count == 0
    assert model.mean_ms is None and model.p95_ms is None and model.p99_ms is None
    assert model.frames_dropped == 0


def test_inference_metrics_snapshot_matches_to_dict():
    metrics = InferenceMetrics(frames_dropped=3)
    for latency in (10.0, 20.0, 30.0, 400.0):
        metrics.record(latency)
    model = InferenceMetricsSnapshot.from_dataclass(metrics)
    assert model.model_dump(exclude={"schema_version"}) == metrics.to_dict()
    assert model.sample_count == 4
    assert model.frames_dropped == 3


def test_telemetry_models_json_roundtrip():
    metrics = InferenceMetrics()
    metrics.record(12.5)
    for model in (
        RuntimeTelemetry.from_dataclass(RuntimeSnapshot(event_count=1)),
        InferenceMetricsSnapshot.from_dataclass(metrics),
    ):
        restored = type(model).model_validate_json(model.model_dump_json())
        assert restored == model


def test_edge_telemetry_composes_both_snapshots():
    metrics = InferenceMetrics()
    metrics.record(7.0)
    model = EdgeTelemetry.from_dataclasses(RuntimeSnapshot(camera_count=1), metrics)
    assert model.runtime.camera_count == 1
    assert model.inference.sample_count == 1
    assert EdgeTelemetry.model_validate_json(model.model_dump_json()) == model
