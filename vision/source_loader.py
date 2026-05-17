from __future__ import annotations
import time
import uuid
from typing import Iterator

from .schemas import InferenceFrame


def synthetic_frames(
    camera_id: str = "cam-001",
    width: int = 1920,
    height: int = 1080,
    fps: float = 10.0,
    count: int | None = None,
) -> Iterator[InferenceFrame]:
    interval_ms = int(1000 / fps)
    base_ts = int(time.time() * 1000)
    i = 0
    while count is None or i < count:
        yield InferenceFrame(
            frame_id=str(uuid.uuid4()),
            camera_id=camera_id,
            timestamp_ms=base_ts + i * interval_ms,
            width=width,
            height=height,
            source_type="synthetic",
        )
        i += 1
