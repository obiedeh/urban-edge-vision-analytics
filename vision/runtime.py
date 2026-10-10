"""EdgeRuntime: owns camera sessions, the model runtime and per-camera inference.

Everything the operator changes in the UI (cameras, model, inference
settings, pack bindings, zones) is applied here without a restart:

* camera create/update/enable → ``refresh_camera``
* camera delete/disable       → ``remove_camera``
* model settings              → ``apply_model_settings``
* inference settings          → ``apply_inference_settings``
* bindings / zones            → ``refresh_bindings``

Video (``CameraSession`` threads) and inference (one asyncio task per camera)
are independent loops joined only by the latest-frame slot.
"""
from __future__ import annotations

import asyncio
import io
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from PIL import Image

from events.schemas import TrafficEvent
from packs.runner import PackRunner
from store.config_store import ConfigStore
from store.event_store import SqliteEventStore
from store.models import CameraRecord, InferenceSettings, ModelSettings
from vision.adapters import detection_prompt, normalize_detections_to_unit
from vision.camera_engine import (
    CameraSession,
    PushCameraSession,
    StreamCameraSession,
    SyntheticCameraSession,
)
from vision.host_capabilities import default_model_for, detect_host
from vision.model_runtime import ModelRuntime
from vision.prompt_presets import preset_focus
from vision.result_broadcaster import InferenceResult, ResultBroadcaster
from vision.schemas import InferenceFrame

logger = logging.getLogger(__name__)

STALE_FRAME_S = 10.0


class EdgeRuntime:
    def __init__(
        self,
        config_store: ConfigStore,
        event_store: SqliteEventStore,
        *,
        publisher: Any = None,
        inference_metrics: Any = None,
        runtime_snapshot: Any = None,
    ) -> None:
        self.config = config_store
        self.events = event_store
        self.publisher = publisher
        self.inference_metrics = inference_metrics
        self.runtime_snapshot = runtime_snapshot
        self.model = ModelRuntime()
        self.inference_settings = InferenceSettings()
        self.broadcaster = ResultBroadcaster()
        self.sessions: dict[str, CameraSession] = {}
        self.runners: dict[str, PackRunner] = {}
        self.cameras: dict[str, CameraRecord] = {}
        self.last_results: dict[str, InferenceResult] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self.host = detect_host()
        self.started_at: float | None = None
        # Model-server events (operator starts/stops, outages) with timestamps,
        # exported in /runtime/status and copied into run artifacts.
        self.server_events: list[dict[str, Any]] = []
        self._outage_started: float | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self.started_at = time.time()
        await self.config.init()
        stored = await self.config.get_setting("model")
        if stored is None:
            default = default_model_for(self.host)
            await self.config.put_model_settings(ModelSettings(**default))
            logger.info(
                "model default chosen for %s: %s", self.host.recommended_profile, default["label"]
            )
        await self.apply_model_settings()
        await self.apply_inference_settings()
        for camera in await self.config.list_cameras():
            if camera.enabled:
                await self.refresh_camera(camera.id)

    async def stop(self) -> None:
        for camera_id in list(self._tasks):
            await self._stop_camera(camera_id)

    # ── configuration hooks ───────────────────────────────────────────────────

    async def apply_model_settings(self) -> None:
        settings = await self.config.get_model_settings()
        api_key = await self.config.get_model_api_key()
        self.model.configure(settings, api_key)

    async def apply_inference_settings(self) -> None:
        self.inference_settings = await self.config.get_inference_settings()
        for session in self.sessions.values():
            session.display_max_width = self.inference_settings.display_max_width
            session.jpeg_quality = self.inference_settings.jpeg_quality

    async def refresh_camera(self, camera_id: str) -> None:
        async with self._lock:
            await self._stop_camera(camera_id)
            camera = await self.config.get_camera(camera_id)
            if camera is None or not camera.enabled:
                self.cameras.pop(camera_id, None)
                self.last_results.pop(camera_id, None)
                return
            self.cameras[camera_id] = camera
            session = await self._build_session(camera)
            self.sessions[camera_id] = session
            session.start()
            runner = PackRunner(camera_id)
            self.runners[camera_id] = runner
            await self._configure_runner(camera_id, runner)
            self._tasks[camera_id] = asyncio.create_task(
                self._inference_loop(camera_id), name=f"inference-{camera_id}"
            )
            if self.runtime_snapshot is not None:
                self.runtime_snapshot.camera_count = len(self.sessions)

    async def remove_camera(self, camera_id: str) -> None:
        async with self._lock:
            await self._stop_camera(camera_id)
            self.cameras.pop(camera_id, None)
            self.last_results.pop(camera_id, None)
            if self.runtime_snapshot is not None:
                self.runtime_snapshot.camera_count = len(self.sessions)

    async def refresh_bindings(self, camera_id: str) -> None:
        runner = self.runners.get(camera_id)
        if runner is not None:
            await self._configure_runner(camera_id, runner)

    async def _configure_runner(self, camera_id: str, runner: PackRunner) -> None:
        bindings = await self.config.get_bindings(camera_id)
        for b in bindings:
            if "parameters_json" in b:
                b["parameters"] = b.pop("parameters_json")
        runner.configure(
            bindings,
            await self.config.get_stop_zone(camera_id),
            await self.config.get_speed_calibration(camera_id),
        )

    async def _build_session(self, camera: CameraRecord) -> CameraSession:
        kw: dict[str, Any] = {
            "display_max_width": self.inference_settings.display_max_width,
            "jpeg_quality": self.inference_settings.jpeg_quality,
        }
        if camera.profile == "synthetic":
            return SyntheticCameraSession(camera.id, **kw)
        if camera.profile == "browser_webrtc":
            return PushCameraSession(camera.id, **kw)
        url = await self.config.feed_url(camera.id)
        return StreamCameraSession(camera.id, url, rtsp_transport=camera.rtsp_transport, **kw)

    async def _stop_camera(self, camera_id: str) -> None:
        task = self._tasks.pop(camera_id, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        session = self.sessions.pop(camera_id, None)
        if session is not None:
            await asyncio.to_thread(session.stop)
        self.runners.pop(camera_id, None)

    def note_server_event(self, kind: str, **detail: Any) -> None:
        event = {"at": datetime.now(UTC).isoformat(), "kind": kind, **detail}
        self.server_events.append(event)
        if len(self.server_events) > 500:
            del self.server_events[: len(self.server_events) - 500]
        logger.warning("model server event: %s", event)

    def _track_outage(self, ok: bool) -> None:
        now = time.time()
        if ok:
            if self._outage_started is not None:
                self.note_server_event(
                    "outage ended", duration_s=round(now - self._outage_started, 1)
                )
                self._outage_started = None
        elif self._outage_started is None:
            self._outage_started = now
            self.note_server_event("outage started", error=self.model.last_error)

    # ── access for routes ─────────────────────────────────────────────────────

    def session(self, camera_id: str) -> CameraSession | None:
        return self.sessions.get(camera_id)

    def push_session(self, camera_id: str) -> PushCameraSession | None:
        session = self.sessions.get(camera_id)
        return session if isinstance(session, PushCameraSession) else None

    def status(self) -> dict[str, Any]:
        cameras = []
        for camera_id, session in self.sessions.items():
            runner = self.runners.get(camera_id)
            result = self.last_results.get(camera_id)
            camera = self.cameras.get(camera_id)
            cameras.append(
                {
                    **session.status(),
                    "name": camera.name if camera else camera_id,
                    "profile": camera.profile if camera else None,
                    "packs": runner.status() if runner else None,
                    "last_inference": (
                        {
                            "status": result.metadata.get("status"),
                            "age_s": round(time.time() - result.timestamp_ms / 1000, 1),
                            "latency_ms": result.inference_latency_ms,
                            "detections": result.vehicle_count,
                        }
                        if result else None
                    ),
                }
            )
        return {
            "started_at": self.started_at,
            "host": self.host.to_dict(),
            "model": {
                **self.model.status(),
                "outage_open_since": (
                    datetime.fromtimestamp(self._outage_started, tz=UTC).isoformat()
                    if self._outage_started else None
                ),
            },
            "server_events": self.server_events[-50:],
            "inference": self.inference_settings.model_dump(),
            "cameras": cameras,
        }

    # ── inference loop ────────────────────────────────────────────────────────

    async def _inference_loop(self, camera_id: str) -> None:
        last_seq = -1
        last_status_publish = 0.0
        while True:
            interval = max(self.inference_settings.interval_ms, 100) / 1000
            await asyncio.sleep(interval)
            session = self.sessions.get(camera_id)
            if session is None:
                return
            record = session.slot.latest
            now = time.time()
            if record is None or (time.monotonic() - record.monotonic) > STALE_FRAME_S:
                if now - last_status_publish > 5.0:
                    await self._publish_status(camera_id, "no_frame", session)
                    last_status_publish = now
                continue
            if record.seq == last_seq and self.model.settings.backend != "mock":
                # Same frame as last time (camera stalled); don't burn GPU on it.
                continue
            last_seq = record.seq
            settings = self.inference_settings
            try:
                frame_bytes, w, h = await asyncio.to_thread(
                    _resize_jpeg, record.jpeg, settings.width, settings.height
                )
            except Exception as exc:
                logger.warning("camera %s: frame resize failed: %s", camera_id, exc)
                continue
            frame = InferenceFrame(
                frame_id=str(uuid.uuid4()),
                camera_id=camera_id,
                timestamp_ms=record.wall_ms,
                width=w,
                height=h,
                source_type=session.kind,
                frame_bytes=frame_bytes,
                metadata={"frame_seq": record.seq, "display_size": [record.width, record.height]},
            )
            prompt = detection_prompt(w, h, preset_focus(settings.prompt_preset))
            try:
                inferred = await self.model.infer(frame, prompt)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._track_outage(False)
                await self._publish_status(camera_id, "inference_unavailable", session)
                continue
            self._track_outage(True)
            inferred = normalize_detections_to_unit(inferred)
            if self.inference_metrics is not None and inferred.inference_latency_ms is not None:
                self.inference_metrics.record(inferred.inference_latency_ms)
            runner = self.runners.get(camera_id)
            pack_events: list[tuple[str, TrafficEvent]] = []
            tracked = inferred
            if runner is not None:
                try:
                    pack_events = await asyncio.to_thread(runner.process, inferred)
                except Exception:
                    logger.exception("pack runner failed for camera %s", camera_id)
                tracked = inferred.model_copy(
                    update={"detections": self._tracked_detections(runner, inferred)}
                )
            for pack_id, event in pack_events:
                await asyncio.to_thread(
                    self.events.add_event, event, pack_id=pack_id, frame_jpeg=frame_bytes
                )
                if self.runtime_snapshot is not None:
                    self.runtime_snapshot.event_count += 1
                if self.publisher is not None:
                    try:
                        self.publisher.publish_event(event)
                    except Exception:  # pragma: no cover - publisher must not break the loop
                        logger.exception("publisher failed")
            result = self._result(camera_id, tracked, pack_events, settings.prompt_preset, record)
            self.last_results[camera_id] = result
            await self.broadcaster.publish(result)

    def _tracked_detections(self, runner: PackRunner, inferred: InferenceFrame) -> list:
        # PackRunner.process already rewrote track ids on its copy; rebuild from tracker state.
        by_box = {
            (round(t.x, 4), round(t.y, 4)): t.track_id for t in runner.tracker.tracks.values()
        }
        out = []
        for det in inferred.detections:
            key = (round(det.bounding_box.x, 4), round(det.bounding_box.y, 4))
            out.append(det.model_copy(update={"track_id": by_box.get(key, det.track_id)}))
        return out

    def _result(
        self,
        camera_id: str,
        inferred: InferenceFrame,
        pack_events: list[tuple[str, TrafficEvent]],
        preset: str,
        record: Any,
    ) -> InferenceResult:
        meta = inferred.metadata
        detections = [
            {
                "track_id": d.track_id,
                "label": d.vehicle_class.value,
                "confidence": round(d.bounding_box.confidence, 3),
                "bbox": [
                    round(d.bounding_box.x, 4), round(d.bounding_box.y, 4),
                    round(d.bounding_box.width, 4), round(d.bounding_box.height, 4),
                ],
            }
            for d in inferred.detections
        ]
        first_event = pack_events[0][1] if pack_events else None
        return InferenceResult(
            result_id=str(uuid.uuid4()),
            camera_id=camera_id,
            frame_id=inferred.frame_id,
            timestamp_ms=inferred.timestamp_ms,
            model_id=self.model.settings.model or self.model.settings.backend,
            prompt_preset=preset,
            vlm_summary=_str_or_none(meta.get("vlm_summary")),
            vlm_reasoning=None,
            raw_response=_str_or_none(meta.get("vlm_response")),
            parse_ok=bool(detections) or bool(meta.get("vlm_summary")),
            vehicle_count=len(inferred.detections),
            inference_latency_ms=inferred.inference_latency_ms,
            event=first_event,
            metadata={
                "status": "ok",
                "detections": detections,
                "frame_seq": record.seq,
                "frame_size": [inferred.width, inferred.height],
                "pack_events": [
                    {"pack_id": pid, "event_id": e.event_id, "event_type": e.event_type.value,
                     "severity": e.severity.value}
                    for pid, e in pack_events
                ],
                "prompt_tokens": meta.get("prompt_tokens"),
                "completion_tokens": meta.get("completion_tokens"),
            },
        )

    async def _publish_status(self, camera_id: str, status: str, session: CameraSession) -> None:
        result = InferenceResult(
            result_id=str(uuid.uuid4()),
            camera_id=camera_id,
            frame_id="",
            timestamp_ms=int(time.time() * 1000),
            model_id=self.model.settings.model or self.model.settings.backend,
            prompt_preset=self.inference_settings.prompt_preset,
            parse_ok=False,
            vehicle_count=0,
            event=None,
            metadata={
                "status": status,
                "detections": [],
                "camera_state": session.stats.state,
                "model_error": self.model.last_error,
            },
        )
        self.last_results[camera_id] = result
        await self.broadcaster.publish(result)


def _resize_jpeg(jpeg: bytes, width: int, height: int) -> tuple[bytes, int, int]:
    image: Image.Image = Image.open(io.BytesIO(jpeg))
    image.load()
    if image.width > width or image.height > height:
        # Preserve aspect ratio inside the configured box.
        scale = min(width / image.width, height / image.height)
        image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))))
    if image.mode != "RGB":
        image = image.convert("RGB")
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    return buf.getvalue(), image.width, image.height


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
