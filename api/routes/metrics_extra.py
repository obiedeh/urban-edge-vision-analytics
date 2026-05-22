from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends

from analytics.flow import FlowWindow
from telemetry.metrics import InferenceMetrics

router = APIRouter(prefix="/metrics", tags=["metrics"])

_MOCK_TOOLTIP = (
    "Mock adapter — does not prove real camera accuracy, Jetson latency, "
    "TensorRT acceleration, or automated enforcement readiness."
)

# Canonical artifact paths (relative to repo root where uvicorn is launched)
_JETSON_ARTIFACT = Path("artifacts/reports/jetson-benchmark.json")


def _get_inference_metrics() -> InferenceMetrics:
    raise RuntimeError("InferenceMetrics not initialised")  # pragma: no cover


def _get_flow() -> FlowWindow | None:
    return None  # pragma: no cover


def _get_adapter_name() -> str:
    return "mock"  # pragma: no cover


# ── Badge helpers (server-side — client never decides data_source) ─────────────

def _data_source(adapter_name: str, source: str = "live") -> str:
    """Canonical data-source string.  Client must use the value from the response."""
    if source == "benchmark_artifact":
        return "validated-benchmark"
    if adapter_name == "mock":
        return "mock"
    return "live-rtsp"


def _badge(adapter_name: str, source: str = "live") -> dict:
    ds = _data_source(adapter_name, source)
    result: dict = {"data_source": ds}
    if ds == "mock":
        result["tooltip"] = _MOCK_TOOLTIP
    return result


def _tile(
    key: str,
    label: str,
    value: float | int | str | None,
    badge: dict,
    unit: str | None = None,
) -> dict:
    """Build one KpiTile dict. badge carries data_source + optional tooltip."""
    t: dict = {"key": key, "label": label, "value": value, **badge}
    if unit is not None:
        t["unit"] = unit
    return t


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/kpis")
def get_kpis(
    inference: InferenceMetrics = Depends(_get_inference_metrics),
    flow: FlowWindow | None = Depends(_get_flow),
    adapter_name: str = Depends(_get_adapter_name),
) -> dict:
    """KPI tiles for S12.  Every tile carries data_source + tooltip (server-side)."""
    badge = _badge(adapter_name)
    inf = inference.to_dict()

    tiles: list[dict] = [
        _tile("latency_mean",  "Latency mean",       inf.get("mean_ms"),     badge, "ms"),
        _tile("latency_p95",   "Latency p95",        inf.get("p95_ms"),      badge, "ms"),
        _tile("latency_p99",   "Latency p99",        inf.get("p99_ms"),      badge, "ms"),
        _tile("sample_count",  "Inference samples",  inf.get("sample_count"), badge),
    ]

    if flow is not None:
        class_counts = flow.class_counts()
        person_count = class_counts.get("pedestrian", 0)
        tiles += [
            _tile("vehicle_count", "Vehicles in frame", flow.vehicle_count, badge),
            _tile("person_count",  "Persons in frame",  person_count,       badge),
            _tile(
                "congestion",
                "Congestion",
                "CONGESTED" if flow.is_congested else "CLEAR",
                badge,
            ),
        ]

    return {"tiles": tiles, "adapter": adapter_name, **badge}


@router.get("/flow")
def get_flow(
    flow: FlowWindow | None = Depends(_get_flow),
    adapter_name: str = Depends(_get_adapter_name),
) -> dict:
    """FlowWindow snapshot — vehicle count, congestion windows, per-class counts."""
    badge = _badge(adapter_name)
    now = datetime.now(UTC).isoformat()

    if flow is None:
        return {
            "window_start": now,
            "window_end":   now,
            "vehicle_count":    0,
            "person_count":     0,
            "congestion_windows": 0,
            "class_counts":     {},
            **badge,
        }

    class_counts = flow.class_counts()
    person_count = class_counts.get("pedestrian", 0)

    return {
        "window_start": now,
        "window_end":   now,
        "vehicle_count":      flow.vehicle_count,
        "person_count":       person_count,
        "congestion_windows": 1 if flow.is_congested else 0,
        "class_counts":       class_counts,
        **badge,
    }


@router.get("/benchmarks")
def get_benchmarks() -> dict:
    """Benchmark cards for S12.

    Reads artifact files if present; returns ``None`` for absent entries so the
    client can render the correct empty-state card with its roadmap pointer.
    Client must never fabricate numbers from this endpoint.
    """
    jetson: dict | None = None
    if _JETSON_ARTIFACT.exists():
        try:
            jetson = json.loads(_JETSON_ARTIFACT.read_text())
        except Exception:
            pass

    return {
        # Phase 3 deliverable — Jetson Thor AGX
        "jetson": jetson,
        # Phase 2 deliverables — not yet run
        "cpu_baseline": None,
        "rtx_dev":      None,
    }
