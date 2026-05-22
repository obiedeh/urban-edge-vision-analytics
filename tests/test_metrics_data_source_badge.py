"""Tests for metrics_extra data-source badge logic.

Verifies that:
- _data_source() returns the correct string for each adapter/source combination
- _badge() always includes data_source; only includes tooltip for "mock"
- /metrics/kpis response shape matches KpisResponse (tiles array + adapter field)
- /metrics/flow response carries data_source
- /metrics/benchmarks returns null entries when artifacts are absent
- Tooltip text matches PORTFOLIO_DELIVERABLES.md verbatim
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app
from api.routes.metrics_extra import _badge, _data_source

_MOCK_TOOLTIP = (
    "Mock adapter — does not prove real camera accuracy, Jetson latency, "
    "TensorRT acceleration, or automated enforcement readiness."
)

client = TestClient(app)


# ── Unit tests for badge helpers ──────────────────────────────────────────────

class TestDataSource:
    def test_mock_adapter(self):
        assert _data_source("mock") == "mock"

    def test_live_rtsp_adapter(self):
        assert _data_source("onnx") == "live-rtsp"
        assert _data_source("tensorrt") == "live-rtsp"
        assert _data_source("nim") == "live-rtsp"

    def test_benchmark_source_overrides_adapter(self):
        assert _data_source("mock",      "benchmark_artifact") == "validated-benchmark"
        assert _data_source("onnx",      "benchmark_artifact") == "validated-benchmark"
        assert _data_source("tensorrt",  "benchmark_artifact") == "validated-benchmark"

    def test_default_source_is_live(self):
        assert _data_source("onnx", "live") == "live-rtsp"


class TestBadge:
    def test_mock_includes_tooltip(self):
        b = _badge("mock")
        assert b["data_source"] == "mock"
        assert "tooltip" in b
        assert b["tooltip"] == _MOCK_TOOLTIP

    def test_live_rtsp_no_tooltip(self):
        b = _badge("onnx")
        assert b["data_source"] == "live-rtsp"
        assert "tooltip" not in b

    def test_benchmark_no_tooltip(self):
        b = _badge("mock", "benchmark_artifact")
        assert b["data_source"] == "validated-benchmark"
        assert "tooltip" not in b

    def test_tooltip_text_verbatim(self):
        """Tooltip MUST match PORTFOLIO_DELIVERABLES.md word-for-word."""
        b = _badge("mock")
        assert b["tooltip"] == (
            "Mock adapter — does not prove real camera accuracy, Jetson latency, "
            "TensorRT acceleration, or automated enforcement readiness."
        )


# ── API response shape tests ──────────────────────────────────────────────────

class TestKpisEndpoint:
    def test_response_has_tiles_and_adapter(self):
        r = client.get("/metrics/kpis")
        assert r.status_code == 200
        body = r.json()
        assert "tiles" in body
        assert "adapter" in body
        assert isinstance(body["tiles"], list)

    def test_tiles_have_required_fields(self):
        body = client.get("/metrics/kpis").json()
        for tile in body["tiles"]:
            assert "key"         in tile, f"tile missing 'key': {tile}"
            assert "label"       in tile, f"tile missing 'label': {tile}"
            assert "value"       in tile, f"tile missing 'value': {tile}"
            assert "data_source" in tile, f"tile missing 'data_source': {tile}"

    def test_mock_tiles_have_tooltip(self):
        """All tiles must carry the tooltip when adapter is mock."""
        body = client.get("/metrics/kpis").json()
        # Default test adapter is mock (dependency override in api/main.py)
        if body["adapter"] == "mock":
            for tile in body["tiles"]:
                assert "tooltip" in tile, f"mock tile missing tooltip: {tile}"
                assert tile["tooltip"] == _MOCK_TOOLTIP

    def test_top_level_data_source_present(self):
        body = client.get("/metrics/kpis").json()
        assert "data_source" in body

    def test_latency_tiles_present(self):
        body = client.get("/metrics/kpis").json()
        keys = {t["key"] for t in body["tiles"]}
        assert "latency_mean" in keys
        assert "latency_p95"  in keys
        assert "sample_count" in keys


class TestFlowEndpoint:
    def test_response_has_data_source(self):
        r = client.get("/metrics/flow")
        assert r.status_code == 200
        body = r.json()
        assert "data_source" in body

    def test_response_shape(self):
        body = client.get("/metrics/flow").json()
        for field in ("vehicle_count", "person_count", "congestion_windows",
                      "class_counts", "window_start", "window_end"):
            assert field in body, f"flow missing field: {field}"


class TestBenchmarksEndpoint:
    def test_response_shape(self):
        r = client.get("/metrics/benchmarks")
        assert r.status_code == 200
        body = r.json()
        assert "jetson"       in body
        assert "cpu_baseline" in body
        assert "rtx_dev"      in body

    def test_empty_state_when_no_artifacts(self, tmp_path, monkeypatch):
        """When artifact files are absent, all entries are None."""
        import api.routes.metrics_extra as me
        monkeypatch.setattr(me, "_JETSON_ARTIFACT", tmp_path / "nonexistent.json")
        body = client.get("/metrics/benchmarks").json()
        assert body["jetson"]       is None
        assert body["cpu_baseline"] is None
        assert body["rtx_dev"]      is None
