from __future__ import annotations

from fastapi import APIRouter, Depends

from analytics.flow import FlowWindow
from telemetry.metrics import InferenceMetrics

router = APIRouter(prefix="/metrics", tags=["metrics"])

_MOCK_TOOLTIP = (
    "Mock adapter — does not prove real camera accuracy, Jetson latency, "
    "TensorRT acceleration, or automated enforcement readiness."
)


def _get_inference_metrics() -> InferenceMetrics:
    raise RuntimeError("InferenceMetrics not initialised")  # pragma: no cover


def _get_flow() -> FlowWindow | None:
    return None  # pragma: no cover


def _get_adapter_name() -> str:
    return "mock"  # pragma: no cover


def _data_source(adapter_name: str, source: str = "live") -> str:
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


@router.get("/kpis")
def get_kpis(
    inference: InferenceMetrics = Depends(_get_inference_metrics),
    flow: FlowWindow | None = Depends(_get_flow),
    adapter_name: str = Depends(_get_adapter_name),
) -> dict:
    """KPI tiles for S12 — every field carries a data_source badge."""
    badge = _badge(adapter_name)

    inf = inference.to_dict()
    kpis: dict = {
        "inference_latency_ms": {
            "mean": inf.get("mean_ms"),
            "p95": inf.get("p95_ms"),
            "sample_count": inf.get("sample_count"),
            **badge,
        },
    }

    if flow is not None:
        kpis["flow"] = {
            "vehicle_count": flow.vehicle_count,
            "is_congested": flow.is_congested,
            "mean_inference_latency_ms": flow.mean_inference_latency_ms,
            "class_counts": flow.class_counts(),
            **badge,
        }

    return {"kpis": kpis, **badge}


@router.get("/flow")
def get_flow(
    flow: FlowWindow | None = Depends(_get_flow),
    adapter_name: str = Depends(_get_adapter_name),
) -> dict:
    """FlowWindow snapshot — vehicle count, congestion windows, per-class counts."""
    badge = _badge(adapter_name)
    if flow is None:
        return {"vehicle_count": 0, "is_congested": False, "class_counts": {}, **badge}
    return {
        "vehicle_count": flow.vehicle_count,
        "is_congested": flow.is_congested,
        "mean_inference_latency_ms": flow.mean_inference_latency_ms,
        "class_counts": flow.class_counts(),
        **badge,
    }
