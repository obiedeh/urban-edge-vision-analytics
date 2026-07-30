import pytest

from vision.adapters import MockDetectionAdapter
from vision.live_pipeline import collect_dual_loop_results, result_to_event_payload
from vision.schemas import InferenceFrame


def _frame(frame_id: str = "frame-1") -> InferenceFrame:
    return InferenceFrame(
        frame_id=frame_id,
        camera_id="cam-1",
        timestamp_ms=1000,
        width=640,
        height=360,
        source_type="synthetic",
    )


@pytest.mark.asyncio
async def test_dual_loop_mock_adapter_emits_result() -> None:
    results = await collect_dual_loop_results(
        [_frame()],
        MockDetectionAdapter(seed=1),
        inference_interval_ms=5,
    )

    assert results
    result = results[0]
    assert result.camera_id == "cam-1"
    assert result.vlm_summary is not None
    assert result.event is not None
    assert result.event.vlm_summary == result.vlm_summary


@pytest.mark.asyncio
async def test_result_to_event_payload_includes_vlm_fields() -> None:
    result = (
        await collect_dual_loop_results(
            [_frame()],
            MockDetectionAdapter(seed=1),
            inference_interval_ms=5,
        )
    )[0]

    payload = result_to_event_payload(result)

    assert payload["vlm_summary"] == result.vlm_summary
    assert payload["vlm_model"] == "mock"
    assert payload["metadata"]["prompt_preset"] == "vehicle_count"

