import asyncio

import pytest

from vision.frame_slot import FrameSlot
from vision.schemas import InferenceFrame


def _frame(frame_id: str) -> InferenceFrame:
    return InferenceFrame(
        frame_id=frame_id,
        camera_id="cam-1",
        timestamp_ms=1000,
        width=640,
        height=360,
    )


@pytest.mark.asyncio
async def test_put_frame_overwrites_existing_frame() -> None:
    slot = FrameSlot()

    slot.put_frame(_frame("old"))
    slot.put_frame(_frame("new"))

    assert (await slot.get_frame()).frame_id == "new"
    assert slot.latest is not None
    assert slot.latest.frame_id == "new"


@pytest.mark.asyncio
async def test_get_frame_waits_until_frame_is_available() -> None:
    slot = FrameSlot()

    task = asyncio.create_task(slot.get_frame())
    await asyncio.sleep(0)
    assert not task.done()

    slot.put_frame(_frame("frame-1"))

    assert (await asyncio.wait_for(task, timeout=1)).frame_id == "frame-1"


@pytest.mark.asyncio
async def test_concurrent_put_get_returns_latest_frame() -> None:
    slot = FrameSlot()

    async def producer() -> None:
        slot.put_frame(_frame("frame-1"))
        slot.put_frame(_frame("frame-2"))

    consumer = asyncio.create_task(slot.get_frame())
    await producer()

    assert (await asyncio.wait_for(consumer, timeout=1)).frame_id == "frame-2"

