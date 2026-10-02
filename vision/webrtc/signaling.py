from __future__ import annotations

import asyncio
import contextlib
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from vision.webrtc.track import IncomingVideoTrack

try:  # pragma: no cover - exercised when aiortc is installed
    from aiortc import RTCPeerConnection, RTCSessionDescription
except ImportError:  # pragma: no cover - tests can inject fakes through dependencies
    RTCPeerConnection = None  # type: ignore[assignment,misc]
    RTCSessionDescription = None  # type: ignore[assignment,misc]

router = APIRouter(tags=["webrtc"])


class WebRTCOffer(BaseModel):
    sdp: str
    type: str
    session_id: str | None = None
    camera_id: str


class WebRTCAnswer(BaseModel):
    session_id: str
    sdp: str
    type: str


def _get_runtime() -> Any:
    raise RuntimeError("EdgeRuntime not initialised")  # pragma: no cover


def _get_sessions() -> dict[str, Any]:
    raise RuntimeError("WebRTC sessions not initialised")  # pragma: no cover


@router.post("/webrtc/offer")
async def create_webrtc_offer_answer(
    offer: WebRTCOffer,
    runtime: Any = Depends(_get_runtime),
    sessions: dict[str, Any] = Depends(_get_sessions),
) -> WebRTCAnswer:
    if RTCPeerConnection is None or RTCSessionDescription is None:
        raise HTTPException(status_code=503, detail="aiortc is not installed")

    push = runtime.push_session(offer.camera_id)
    if push is None:
        raise HTTPException(
            status_code=404,
            detail="Camera is not an enabled browser_webrtc camera. Add one in Cameras first.",
        )

    peer = RTCPeerConnection()
    session_id = offer.session_id or str(uuid.uuid4())
    sessions[session_id] = peer

    @peer.on("track")
    def on_track(track: Any) -> None:
        if getattr(track, "kind", "") != "video":
            return
        incoming = IncomingVideoTrack(track, push.push_image)
        task = asyncio.create_task(incoming.consume())

        @track.on("ended")
        async def on_ended() -> None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            push.stats.state = "connecting"

    remote = RTCSessionDescription(sdp=offer.sdp, type=offer.type)
    await peer.setRemoteDescription(remote)
    answer = await peer.createAnswer()
    await peer.setLocalDescription(answer)

    local = peer.localDescription
    return WebRTCAnswer(session_id=session_id, sdp=local.sdp, type=local.type)


@router.delete("/webrtc/{session_id}", status_code=204)
async def close_webrtc_session(
    session_id: str, sessions: dict[str, Any] = Depends(_get_sessions)
) -> None:
    peer = sessions.pop(session_id, None)
    if peer is None:
        return
    close = getattr(peer, "close", None)
    if close is not None:
        result = close()
        if asyncio.iscoroutine(result):
            await result


async def close_peer_connections(sessions: dict[str, Any]) -> None:
    peers = list(sessions.values())
    sessions.clear()
    for peer in peers:
        close = getattr(peer, "close", None)
        if close is None:
            continue
        result = close()
        if asyncio.iscoroutine(result):
            await result
