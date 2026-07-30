from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vision.frame_slot import FrameSlot
from vision.webrtc import signaling


@dataclass
class FakeSessionDescription:
    sdp: str
    type: str


class FakePeerConnection:
    def __init__(self) -> None:
        self.localDescription: FakeSessionDescription | None = None
        self.remote: FakeSessionDescription | None = None
        self.handlers: dict[str, Any] = {}
        self.closed = False

    def on(self, event_name: str):
        def register(handler):
            self.handlers[event_name] = handler
            return handler

        return register

    async def setRemoteDescription(self, description: FakeSessionDescription) -> None:
        self.remote = description

    async def createAnswer(self) -> FakeSessionDescription:
        return FakeSessionDescription(sdp="answer-sdp", type="answer")

    async def setLocalDescription(self, description: FakeSessionDescription) -> None:
        self.localDescription = description

    async def close(self) -> None:
        self.closed = True


def test_webrtc_offer_answer_round_trip(monkeypatch) -> None:
    sessions: dict[str, Any] = {}
    app = FastAPI()
    app.include_router(signaling.router)
    app.dependency_overrides[signaling._get_frame_slot] = lambda: FrameSlot()
    app.dependency_overrides[signaling._get_sessions] = lambda: sessions
    monkeypatch.setattr(signaling, "RTCPeerConnection", FakePeerConnection)
    monkeypatch.setattr(signaling, "RTCSessionDescription", FakeSessionDescription)

    response = TestClient(app).post(
        "/webrtc/offer",
        json={"sdp": "offer-sdp", "type": "offer", "camera_id": "cam-1"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["sdp"] == "answer-sdp"
    assert data["type"] == "answer"
    assert data["session_id"] in sessions

