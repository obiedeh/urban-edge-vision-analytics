from __future__ import annotations

import asyncio

from vision.schemas import InferenceFrame


class FrameSlot:
    """Single-frame async slot that always keeps the freshest frame."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[InferenceFrame] = asyncio.Queue(maxsize=1)
        self._latest: InferenceFrame | None = None

    @property
    def latest(self) -> InferenceFrame | None:
        return self._latest

    def put_frame(self, frame: InferenceFrame) -> None:
        self._latest = frame
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover - defensive race guard
                pass
        self._queue.put_nowait(frame)

    async def get_frame(self) -> InferenceFrame:
        frame = await self._queue.get()
        self._latest = frame
        return frame

