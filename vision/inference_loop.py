from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from events.schemas import EventType, Severity, TrafficEvent
from vision.adapters import DetectionAdapter
from vision.frame_slot import FrameSlot
from vision.prompt_parsers import (
    DEFAULT_PROMPT_PRESET,
    parse_prompt_response,
    prompt_for_preset,
)
from vision.result_broadcaster import InferenceResult, ResultBroadcaster
from vision.schemas import InferenceFrame

logger = logging.getLogger(__name__)


class InferenceLoop:
    """Samples the latest frame at a fixed cadence and publishes VLM results."""

    def __init__(
        self,
        frame_slot: FrameSlot,
        adapter: DetectionAdapter,
        broadcaster: ResultBroadcaster,
        *,
        inference_interval_ms: int = 1000,
        model_id: str = "mock",
        prompt_preset: str = DEFAULT_PROMPT_PRESET,
        target_resolution: str = "640x360",
    ) -> None:
        self._frame_slot = frame_slot
        self._adapter = adapter
        self._broadcaster = broadcaster
        self._inference_interval_ms = inference_interval_ms
        self._model_id = model_id
        self._prompt_preset = prompt_preset
        self._target_resolution = target_resolution
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._settings_lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def inference_interval_ms(self) -> int:
        return self._inference_interval_ms

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def prompt_preset(self) -> str:
        return self._prompt_preset

    @property
    def target_resolution(self) -> str:
        return self._target_resolution

    async def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="urban-edge-inference-loop")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def infer_once(self, frame: InferenceFrame | None = None) -> InferenceResult:
        selected_frame = frame or self._frame_slot.latest or await self._frame_slot.get_frame()
        async with self._settings_lock:
            adapter = self._adapter
            prompt_preset = self._prompt_preset
            model_id = self._model_id

        prompt = prompt_for_preset(prompt_preset)
        inferred = await asyncio.to_thread(adapter.infer, selected_frame, prompt)
        return self._result_from_frame(inferred, model_id, prompt_preset)

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            interval_s = max(self._inference_interval_ms, 1) / 1000
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval_s)
                break
            except TimeoutError:
                pass

            frame = self._frame_slot.latest
            if frame is None:
                continue

            try:
                result = await self.infer_once(frame)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Live inference failed; continuing loop")
                continue
            await self._broadcaster.publish(result)

    def _result_from_frame(
        self,
        frame: InferenceFrame,
        model_id: str,
        prompt_preset: str,
    ) -> InferenceResult:
        raw_response = _string_metadata(frame, "vlm_response")
        parsed = parse_prompt_response(prompt_preset, raw_response)
        event = _traffic_event_from_frame(frame, parsed.summary, parsed.reasoning, model_id)
        return InferenceResult(
            result_id=str(uuid.uuid4()),
            camera_id=frame.camera_id,
            frame_id=frame.frame_id,
            timestamp_ms=frame.timestamp_ms,
            model_id=model_id,
            prompt_preset=prompt_preset,
            vlm_summary=parsed.summary,
            vlm_reasoning=parsed.reasoning,
            raw_response=raw_response,
            parse_ok=parsed.parse_ok,
            vehicle_count=len(frame.detections),
            inference_latency_ms=frame.inference_latency_ms,
            event=event,
            metadata={
                "target_resolution": self._target_resolution,
                "structured": parsed.structured,
            },
        )


def _traffic_event_from_frame(
    frame: InferenceFrame,
    vlm_summary: str | None,
    vlm_reasoning: str | None,
    vlm_model: str,
) -> TrafficEvent:
    has_detections = bool(frame.detections)
    confidence = max((d.bounding_box.confidence for d in frame.detections), default=1.0)
    return TrafficEvent(
        event_id=str(uuid.uuid4()),
        camera_id=frame.camera_id,
        event_type=EventType.vehicle_detected if has_detections else EventType.scene_clear,
        severity=Severity.info,
        timestamp=datetime.fromtimestamp(frame.timestamp_ms / 1000, tz=UTC),
        vehicle_count=len(frame.detections),
        track_ids=[d.track_id for d in frame.detections],
        confidence=confidence,
        operator_review_recommended=False,
        vlm_summary=vlm_summary,
        vlm_reasoning=vlm_reasoning,
        vlm_model=vlm_model,
        metadata={
            "source_type": frame.source_type,
            "frame_id": frame.frame_id,
        },
    )


def _string_metadata(frame: InferenceFrame, key: str) -> str:
    value = frame.metadata.get(key)
    return value if isinstance(value, str) else ""
