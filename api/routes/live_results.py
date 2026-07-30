from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from vision.result_broadcaster import ResultBroadcaster

router = APIRouter(prefix="/live", tags=["live"])


def _get_broadcaster() -> ResultBroadcaster:
    raise RuntimeError("ResultBroadcaster not initialised")  # pragma: no cover


@router.get("/results")
async def stream_live_results(
    request: Request,
    broadcaster: ResultBroadcaster = Depends(_get_broadcaster),
) -> EventSourceResponse:
    async def events():
        async with broadcaster.subscribe() as queue:
            while not await request.is_disconnected():
                try:
                    result = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                yield {
                    "event": "inference_result",
                    "data": result.model_dump_json(),
                }

    return EventSourceResponse(events())
