from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from transports.snapshot import SnapshotTransport

router = APIRouter(prefix="/stream", tags=["stream"])


def _get_transport() -> SnapshotTransport:
    """Overridden in api/main.py after the transport is created."""
    raise RuntimeError("SnapshotTransport not initialised")  # pragma: no cover


@router.get("/{camera_id}/snapshot.jpg", response_class=Response)
def get_snapshot(
    camera_id: str,
    transport: SnapshotTransport = Depends(_get_transport),
) -> Response:
    """Return the latest annotated JPEG for a camera.

    The client is responsible for cache-busting via a ?t=<ms> query parameter.
    """
    jpeg = transport.get_jpeg(camera_id)
    last_updated = transport.last_updated(camera_id) or time.time()
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store",
            "X-Camera-Id": camera_id,
            "X-Last-Updated": str(int(last_updated * 1000)),
        },
    )


@router.post("/{camera_id}/snapshot.jpg", status_code=204)
async def post_snapshot(
    camera_id: str,
    request: Request,
    transport: SnapshotTransport = Depends(_get_transport),
) -> Response:
    """Accept a JPEG frame from the pipeline subprocess and store it in memory.

    The pipeline runs in a separate process and cannot directly access the
    in-memory SnapshotTransport, so it POSTs frames here via HTTP instead.
    """
    body = await request.body()
    if body and len(body) > 100:  # sanity: ignore tiny/empty payloads
        transport.update(camera_id, body)
    return Response(status_code=204)
