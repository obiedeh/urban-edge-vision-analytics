"""Single configurable model endpoint shared by every camera's inference loop.

The adapter is rebuilt atomically when the operator changes backend, endpoint
or model in the UI, so a switch applies to the running loops without a
restart. Health is tracked here so the Live page can show "inference
unavailable" instead of fabricating "scene clear" events.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from typing import Any

from store.models import ModelSettings
from vision.adapters import DetectionAdapter, MockDetectionAdapter, OpenAIVisionAdapter
from vision.redaction import REDACTOR
from vision.schemas import InferenceFrame

logger = logging.getLogger(__name__)


def build_adapter(settings: ModelSettings, api_key: str = "") -> DetectionAdapter:
    if settings.backend == "mock":
        return MockDetectionAdapter()
    return OpenAIVisionAdapter(
        endpoint=settings.normalized_endpoint(),
        model=settings.model,
        api_key=api_key or None,
        think=settings.think,
        max_tokens=settings.max_tokens,
        timeout_s=settings.timeout_s,
        provider=settings.backend,
    )


class ModelRuntime:
    def __init__(self, settings: ModelSettings | None = None, api_key: str = "") -> None:
        self._lock = threading.Lock()
        self._settings = settings or ModelSettings()
        self._adapter: DetectionAdapter = build_adapter(self._settings, api_key)
        self._latencies: deque[float] = deque(maxlen=500)
        self.last_ok_at: float | None = None
        self.last_error: str | None = None
        self.last_error_at: float | None = None
        self.consecutive_failures = 0
        self.total_calls = 0
        self.total_failures = 0
        self.configured_at = time.time()
        self._inflight = asyncio.Semaphore(2)

    @property
    def settings(self) -> ModelSettings:
        return self._settings

    @property
    def adapter(self) -> DetectionAdapter:
        return self._adapter

    def configure(self, settings: ModelSettings, api_key: str = "") -> None:
        adapter = build_adapter(settings, api_key)
        with self._lock:
            self._settings = settings
            self._adapter = adapter
            self.consecutive_failures = 0
            self.last_error = None
            self.configured_at = time.time()
        logger.info(
            "model runtime configured backend=%s model=%s endpoint=%s",
            settings.backend, settings.model, settings.normalized_endpoint(),
        )

    @property
    def healthy(self) -> bool:
        warmed = self.total_calls > 0 or self._settings.backend == "mock"
        return self.consecutive_failures == 0 and warmed

    @property
    def state(self) -> str:
        if self.total_calls == 0:
            return "idle"
        return "healthy" if self.consecutive_failures == 0 else "unavailable"

    async def infer(self, frame: InferenceFrame, prompt: str) -> InferenceFrame:
        with self._lock:
            adapter = self._adapter
        async with self._inflight:
            started = time.perf_counter()
            try:
                inferred = await asyncio.to_thread(adapter.infer, frame, prompt)
            except Exception as exc:
                self._record_failure(exc)
                raise
            self._record_success((time.perf_counter() - started) * 1000)
            return inferred

    def _record_success(self, latency_ms: float) -> None:
        self.total_calls += 1
        self.consecutive_failures = 0
        self.last_ok_at = time.time()
        self._latencies.append(latency_ms)

    def _record_failure(self, exc: BaseException) -> None:
        self.total_calls += 1
        self.total_failures += 1
        self.consecutive_failures += 1
        self.last_error = REDACTOR.redact(str(exc)) or exc.__class__.__name__
        self.last_error_at = time.time()

    def latency_summary(self) -> dict[str, float | int | None]:
        values = sorted(self._latencies)
        if not values:
            return {"n": 0, "p50_ms": None, "p95_ms": None, "mean_ms": None}

        def pct(p: float) -> float:
            idx = min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))
            return round(values[idx], 1)

        return {
            "n": len(values),
            "p50_ms": pct(50),
            "p95_ms": pct(95),
            "mean_ms": round(sum(values) / len(values), 1),
        }

    def status(self) -> dict[str, Any]:
        s = self._settings
        return {
            "backend": s.backend,
            "model": s.model,
            "endpoint": s.normalized_endpoint(),
            "label": s.label,
            "think": s.think,
            "state": self.state,
            "healthy": self.healthy,
            "consecutive_failures": self.consecutive_failures,
            "total_calls": self.total_calls,
            "total_failures": self.total_failures,
            "last_ok_at": self.last_ok_at,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at,
            "latency": self.latency_summary(),
        }
