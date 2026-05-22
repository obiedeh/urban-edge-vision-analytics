from __future__ import annotations

import time

# Minimal 1×1 white JPEG (no model dependency — pure bytes)
_BLANK_JPEG: bytes = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04"
    b"\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa"
    b"\x07\"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br"
    b"\x82\t\n\x16\x17\x18\x19\x1a%&'()*456789:CDEFGHIJ"
    b"STUVWXYZ\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xf5\x7f\xff\xd9"
)


class SnapshotTransport:
    """Serves annotated JPEG snapshots for operator camera views.

    At MVP the pipeline does not persist rendered frames to disk, so this
    transport returns the last frame bytes held in memory per camera.  When
    no frame is available it returns a synthetic placeholder JPEG.

    The cache-bust parameter (`t=<timestamp_ms>`) is appended by the client
    (or the route) — this class does not enforce it; it simply provides the
    bytes for the response.
    """

    def __init__(self) -> None:
        self._frames: dict[str, bytes] = {}
        self._timestamps: dict[str, float] = {}

    def update(self, camera_id: str, jpeg_bytes: bytes) -> None:
        """Store the latest annotated JPEG frame for a camera."""
        self._frames[camera_id] = jpeg_bytes
        self._timestamps[camera_id] = time.time()

    def get_jpeg(self, camera_id: str) -> bytes:
        """Return the latest JPEG for *camera_id*, or a placeholder if none."""
        return self._frames.get(camera_id, _make_placeholder_jpeg(camera_id))

    def last_updated(self, camera_id: str) -> float | None:
        return self._timestamps.get(camera_id)


def _make_placeholder_jpeg(camera_id: str) -> bytes:
    """Return a simple synthetic JPEG placeholder (no OpenCV dependency)."""
    # Use the pre-built blank JPEG — good enough for UI placeholder at MVP
    return _BLANK_JPEG
