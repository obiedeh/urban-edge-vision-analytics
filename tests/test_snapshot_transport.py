from __future__ import annotations

import pytest

from transports.snapshot import SnapshotTransport


@pytest.fixture
def transport() -> SnapshotTransport:
    return SnapshotTransport()


def test_get_jpeg_returns_placeholder_for_unknown_camera(transport: SnapshotTransport) -> None:
    jpeg = transport.get_jpeg("cam-unknown")
    assert isinstance(jpeg, bytes)
    assert len(jpeg) > 0
    # Valid JPEG starts with FF D8
    assert jpeg[:2] == b"\xff\xd8"


def test_update_stores_frame(transport: SnapshotTransport) -> None:
    # Minimal valid JPEG bytes (just the SOI marker for test purposes)
    fake_jpeg = b"\xff\xd8\xff\xd9"
    transport.update("cam-1", fake_jpeg)
    assert transport.get_jpeg("cam-1") == fake_jpeg


def test_last_updated_none_before_update(transport: SnapshotTransport) -> None:
    assert transport.last_updated("cam-1") is None


def test_last_updated_set_after_update(transport: SnapshotTransport) -> None:
    transport.update("cam-1", b"\xff\xd8\xff\xd9")
    ts = transport.last_updated("cam-1")
    assert ts is not None
    assert ts > 0.0


def test_multiple_cameras_independent(transport: SnapshotTransport) -> None:
    transport.update("cam-1", b"\xff\xd8\x01\xff\xd9")
    transport.update("cam-2", b"\xff\xd8\x02\xff\xd9")
    assert transport.get_jpeg("cam-1") != transport.get_jpeg("cam-2")


def test_placeholder_is_valid_jpeg(transport: SnapshotTransport) -> None:
    jpeg = transport.get_jpeg("nonexistent")
    # Check SOI and EOI markers
    assert jpeg[:2] == b"\xff\xd8"
    assert jpeg[-2:] == b"\xff\xd9"
