from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pydantic import BaseModel, Field

from events.schemas import TrafficEvent


class InferenceResult(BaseModel):
    result_id: str
    camera_id: str
    frame_id: str
    timestamp_ms: int
    model_id: str
    prompt_preset: str
    vlm_summary: str | None = None
    vlm_reasoning: str | None = None
    raw_response: str | None = None
    parse_ok: bool = False
    vehicle_count: int = 0
    inference_latency_ms: float | None = None
    event: TrafficEvent | None = None
    metadata: dict = Field(default_factory=dict)


class ResultBroadcaster:
    """Async pub/sub fan-out for live inference results."""

    def __init__(self, subscriber_queue_size: int = 10) -> None:
        self._subscriber_queue_size = subscriber_queue_size
        self._subscribers: set[asyncio.Queue[InferenceResult]] = set()
        self._lock = asyncio.Lock()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[InferenceResult]]:
        queue: asyncio.Queue[InferenceResult] = asyncio.Queue(
            maxsize=self._subscriber_queue_size
        )
        async with self._lock:
            self._subscribers.add(queue)
        try:
            yield queue
        finally:
            async with self._lock:
                self._subscribers.discard(queue)

    async def publish(self, result: InferenceResult) -> None:
        async with self._lock:
            subscribers = list(self._subscribers)

        for queue in subscribers:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:  # pragma: no cover - defensive race guard
                    pass
            queue.put_nowait(result)

