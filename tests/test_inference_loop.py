import asyncio
import time

import pytest

from vision.adapters import DetectionAdapter, MockDetectionAdapter
from vision.frame_slot import FrameSlot
from vision.inference_loop import InferenceLoop
from vision.result_broadcaster import ResultBroadcaster
from vision.schemas import InferenceFrame


def _frame(frame_id: str = "frame-1") -> InferenceFrame:
    return InferenceFrame(
        frame_id=frame_id,
        camera_id="cam-1",
        timestamp_ms=1000,
        width=640,
        height=360,
    )


class FailsOnceAdapter(DetectionAdapter):
    def __init__(self) -> None:
        self.calls = 0
        self._fallback = MockDetectionAdapter(seed=1)

    def infer(self, frame: InferenceFrame, prompt: str = "") -> InferenceFrame:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary model failure")
        return self._fallback.infer(frame, prompt)


class BlockingAdapter(DetectionAdapter):
    def __init__(self) -> None:
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self._fallback = MockDetectionAdapter(seed=1)

    def infer(self, frame: InferenceFrame, prompt: str = "") -> InferenceFrame:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.04)
            return self._fallback.infer(frame, prompt)
        finally:
            self.active -= 1


@pytest.mark.asyncio
async def test_infer_once_populates_vlm_fields() -> None:
    slot = FrameSlot()
    broadcaster = ResultBroadcaster()
    loop = InferenceLoop(
        slot,
        MockDetectionAdapter(seed=1),
        broadcaster,
        model_id="mock",
        prompt_preset="vehicle_count",
    )

    result = await loop.infer_once(_frame())

    assert result.vlm_summary is not None
    assert result.event is not None
    assert result.event.vlm_model == "mock"


@pytest.mark.asyncio
async def test_loop_continues_after_adapter_exception() -> None:
    slot = FrameSlot()
    broadcaster = ResultBroadcaster()
    adapter = FailsOnceAdapter()
    loop = InferenceLoop(slot, adapter, broadcaster, inference_interval_ms=5)
    slot.put_frame(_frame())

    await loop.start()
    try:
        async with broadcaster.subscribe() as queue:
            result = await asyncio.wait_for(queue.get(), timeout=1)
            assert result.camera_id == "cam-1"
            assert adapter.calls >= 2
    finally:
        await loop.stop()


@pytest.mark.asyncio
async def test_busy_inference_does_not_compound() -> None:
    slot = FrameSlot()
    broadcaster = ResultBroadcaster()
    adapter = BlockingAdapter()
    loop = InferenceLoop(slot, adapter, broadcaster, inference_interval_ms=5)
    slot.put_frame(_frame())

    await loop.start()
    await asyncio.sleep(0.12)
    await loop.stop()

    assert adapter.calls >= 1
    assert adapter.max_active == 1

