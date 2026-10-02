"""Video transport to the browser: MJPEG multipart stream and single snapshots.

Frames come straight from the camera session's latest-frame slot, so the
stream runs at the camera's native rate regardless of inference.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

router = APIRouter(prefix="/stream", tags=["stream"])

_BOUNDARY = "urbanedgeframe"


def _get_runtime() -> Any:
    raise RuntimeError("EdgeRuntime not initialised")  # pragma: no cover


@router.get("/{camera_id}/snapshot.jpg")
async def snapshot(camera_id: str, runtime: Any = Depends(_get_runtime)) -> Response:
    session = runtime.session(camera_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Camera is not running")
    record = session.slot.latest
    if record is None:
        raise HTTPException(status_code=503, detail="No frame received yet")
    return Response(
        content=record.jpeg,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store",
            "X-Frame-Seq": str(record.seq),
            "X-Frame-Width": str(record.width),
            "X-Frame-Height": str(record.height),
        },
    )


@router.get("/{camera_id}/live.mjpeg")
async def live_mjpeg(
    camera_id: str,
    request: Request,
    runtime: Any = Depends(_get_runtime),
    max_fps: float = 30.0,
) -> StreamingResponse:
    session = runtime.session(camera_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Camera is not running")
    min_interval = 1.0 / max(1.0, min(max_fps, 60.0))

    async def generate():
        last_seq = -1
        last_sent = 0.0
        loop = asyncio.get_running_loop()
        while not await request.is_disconnected():
            current = runtime.session(camera_id)
            if current is None:
                break
            record = await loop.run_in_executor(None, current.slot.wait_newer, last_seq, 1.0)
            if record is None:
                continue
            now = loop.time()
            if now - last_sent < min_interval:
                last_seq = record.seq
                continue
            last_seq = record.seq
            last_sent = now
            yield (
                f"--{_BOUNDARY}\r\n"
                "Content-Type: image/jpeg\r\n"
                f"Content-Length: {len(record.jpeg)}\r\n"
                f"X-Frame-Seq: {record.seq}\r\n\r\n"
            ).encode() + record.jpeg + b"\r\n"

    return StreamingResponse(
        generate(),
        media_type=f"multipart/x-mixed-replace; boundary={_BOUNDARY}",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/{camera_id}/status")
async def stream_status(camera_id: str, runtime: Any = Depends(_get_runtime)) -> dict:
    session = runtime.session(camera_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Camera is not running")
    return session.status()
