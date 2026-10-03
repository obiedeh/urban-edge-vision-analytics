from __future__ import annotations

from collections.abc import Callable
from typing import Any

try:  # pragma: no cover - exercised when aiortc is installed
    from aiortc import MediaStreamTrack
except ImportError:  # pragma: no cover - keeps test envs without aiortc importable
    MediaStreamTrack = object  # type: ignore[assignment, misc]


class IncomingVideoTrack(MediaStreamTrack):  # type: ignore[misc]
    """Wrap a received WebRTC track and hand decoded frames to a callback.

    The callback receives a PIL image; the camera runtime's PushCameraSession
    JPEG-encodes it into the same latest-frame slot every other camera uses.
    """

    kind = "video"

    def __init__(self, source_track: Any, on_image: Callable[[Any], None]) -> None:
        try:
            super().__init__()
        except TypeError:
            pass
        self._source_track = source_track
        self._on_image = on_image
        self.frames = 0

    async def recv(self) -> Any:
        video_frame = await self._source_track.recv()
        try:
            image = video_frame.to_image()
        except Exception:
            return video_frame
        self.frames += 1
        self._on_image(image)
        return video_frame

    async def consume(self) -> None:
        while True:
            await self.recv()
