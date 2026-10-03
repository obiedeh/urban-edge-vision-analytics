from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from vision.result_broadcaster import ResultBroadcaster

router = APIRouter(prefix="/live", tags=["live"])


def _get_broadcaster() -> ResultBroadcaster:
    raise RuntimeError("ResultBroadcaster not initialised")  # pragma: no cover


def _get_runtime() -> Any:
    return None


@router.get("/results")
async def stream_live_results(
    request: Request,
    camera_id: str | None = None,
    broadcaster: ResultBroadcaster = Depends(_get_broadcaster),
    runtime: Any = Depends(_get_runtime),
) -> EventSourceResponse:
    """Server-sent inference results. ``?camera_id=`` limits to one camera.

    The most recent result per camera is replayed on connect so a freshly
    opened Live page shows the current state instead of waiting a cycle.
    """

    async def events():
        if runtime is not None:
            for cid, last in list(runtime.last_results.items()):
                if camera_id is None or cid == camera_id:
                    yield {"event": "inference_result", "data": last.model_dump_json()}
        async with broadcaster.subscribe() as queue:
            while not await request.is_disconnected():
                try:
                    result = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                if camera_id is not None and result.camera_id != camera_id:
                    continue
                yield {"event": "inference_result", "data": result.model_dump_json()}

    return EventSourceResponse(events())


@router.get("/latest")
async def latest_results(runtime: Any = Depends(_get_runtime)) -> dict:
    if runtime is None:
        return {}
    return {cid: r.model_dump(mode="json") for cid, r in runtime.last_results.items()}
