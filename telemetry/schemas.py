"""Pydantic contracts for telemetry payloads.

``RuntimeSnapshot`` and ``InferenceMetrics`` are mutable dataclasses that
accumulate state. These models are their point-in-time, serializable form:
the same fields the ``/runtime`` and ``/metrics/inference`` endpoints return,
so a cloud payload built from them matches what an operator sees locally.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .metrics import InferenceMetrics
from .runtime import RuntimeSnapshot


class RuntimeTelemetry(BaseModel):
    schema_version: Literal[1] = 1
    uptime_seconds: float
    camera_count: int
    event_count: int
    incident_count: int

    @classmethod
    def from_dataclass(cls, snapshot: RuntimeSnapshot) -> RuntimeTelemetry:
        return cls.model_validate(snapshot.to_dict())


class InferenceMetricsSnapshot(BaseModel):
    schema_version: Literal[1] = 1
    sample_count: int
    mean_ms: float | None = None
    p95_ms: float | None = None
    p99_ms: float | None = None
    frames_dropped: int = 0

    @classmethod
    def from_dataclass(cls, metrics: InferenceMetrics) -> InferenceMetricsSnapshot:
        return cls.model_validate(metrics.to_dict())


class EdgeTelemetry(BaseModel):
    """One telemetry message from an edge node: runtime counters + inference latency."""

    schema_version: Literal[1] = 1
    runtime: RuntimeTelemetry
    inference: InferenceMetricsSnapshot

    @classmethod
    def from_dataclasses(
        cls, runtime: RuntimeSnapshot, metrics: InferenceMetrics
    ) -> EdgeTelemetry:
        return cls(
            runtime=RuntimeTelemetry.from_dataclass(runtime),
            inference=InferenceMetricsSnapshot.from_dataclass(metrics),
        )
