import asyncio

import pytest

from vision.result_broadcaster import InferenceResult, ResultBroadcaster


def _result(result_id: str = "result-1") -> InferenceResult:
    return InferenceResult(
        result_id=result_id,
        camera_id="cam-1",
        frame_id="frame-1",
        timestamp_ms=1000,
        model_id="mock",
        prompt_preset="vehicle_count",
    )


@pytest.mark.asyncio
async def test_multiple_subscribers_each_receive_result() -> None:
    broadcaster = ResultBroadcaster()

    async with broadcaster.subscribe() as q1, broadcaster.subscribe() as q2:
        await broadcaster.publish(_result())

        assert (await asyncio.wait_for(q1.get(), timeout=1)).result_id == "result-1"
        assert (await asyncio.wait_for(q2.get(), timeout=1)).result_id == "result-1"


@pytest.mark.asyncio
async def test_subscriber_cleanup_removes_queue() -> None:
    broadcaster = ResultBroadcaster()

    async with broadcaster.subscribe():
        assert broadcaster.subscriber_count == 1

    assert broadcaster.subscriber_count == 0


@pytest.mark.asyncio
async def test_full_subscriber_queue_keeps_freshest_result() -> None:
    broadcaster = ResultBroadcaster(subscriber_queue_size=1)

    async with broadcaster.subscribe() as queue:
        await broadcaster.publish(_result("old"))
        await broadcaster.publish(_result("new"))

        assert (await asyncio.wait_for(queue.get(), timeout=1)).result_id == "new"

