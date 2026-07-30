from __future__ import annotations

import io
import time
import uuid
from typing import Any

from vision.frame_slot import FrameSlot
from vision.schemas import InferenceFrame

try:  # pragma: no cover - exercised when aiortc is installed
    from aiortc import MediaStreamTrack
except ImportError:  # pragma: no cover - keeps test envs without aiortc importable
    MediaStreamTrack = object  # type: ignore[assignment, misc]


class IncomingVideoTrack(MediaStreamTrack):  # type: ignore[misc]
    """Wrap a received WebRTC track and publish decoded frames into FrameSlot."""

    kind = "video"

    def __init__(
        self,
        source_track: Any,
        frame_slot: FrameSlot,
        *,
        camera_id: str = "browser-camera",
    ) -> None:
        try:
            super().__init__()
        except TypeError:
            pass
        self._source_track = source_track
        self._frame_slot = frame_slot
        self._camera_id = camera_id

    async def recv(self) -> Any:
        video_frame = await self._source_track.recv()
        self._frame_slot.put_frame(self._to_inference_frame(video_frame))
        return video_frame

    async def consume(self) -> None:
        while True:
            await self.recv()

    def _to_inference_frame(self, video_frame: Any) -> InferenceFrame:
        width = int(getattr(video_frame, "width", 0) or 0)
        height = int(getattr(video_frame, "height", 0) or 0)
        timestamp_ms = int(time.time() * 1000)
        return InferenceFrame(
            frame_id=str(uuid.uuid4()),
            camera_id=self._camera_id,
            timestamp_ms=timestamp_ms,
            width=width,
            height=height,
            source_type="webrtc",
            frame_bytes=_encode_video_frame_jpeg(video_frame),
            metadata={"webrtc": True},
        )


def _encode_video_frame_jpeg(video_frame: Any) -> bytes | None:
    try:
        image = video_frame.to_image()
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=82)
        return buffer.getvalue()
    except Exception:
        return None

