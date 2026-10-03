"""EdgeRuntime end to end with a synthetic camera and the mock model.

Proves the two loops are decoupled: video frames keep flowing while the model
is unavailable, and pack events reach the SQLite event store.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from store.config_store import ConfigStore
from store.event_store import SqliteEventStore
from store.models import CameraIn, InferenceSettings, ModelSettings
from store.secrets import SecretBox
from vision.adapters import DetectionAdapter
from vision.camera_engine import SyntheticCameraSession
from vision.runtime import EdgeRuntime
from vision.schemas import BoundingBox, InferenceFrame, VehicleClass, VehicleDetection


class PersonAdapter(DetectionAdapter):
    """Always sees one pedestrian in the middle of the frame."""

    def infer(self, frame: InferenceFrame, prompt: str = "") -> InferenceFrame:
        det = VehicleDetection(
            track_id="x", vehicle_class=VehicleClass.pedestrian,
            bounding_box=BoundingBox(x=0.45 * frame.width, y=0.4 * frame.height,
                                     width=0.1 * frame.width, height=0.3 * frame.height,
                                     confidence=0.9),
            frame_id=frame.frame_id, timestamp_ms=frame.timestamp_ms,
        )
        return frame.model_copy(update={"detections": [det], "inference_latency_ms": 3.0,
                                        "metadata": {"vlm_summary": "one person"}})


class BrokenAdapter(DetectionAdapter):
    def infer(self, frame: InferenceFrame, prompt: str = "") -> InferenceFrame:
        raise ConnectionError("vLLM at rtsp://u:pw@nowhere is down")


@pytest.fixture
async def runtime(tmp_path):
    db = str(tmp_path / "rt.sqlite")
    config = ConfigStore(db, secrets=SecretBox(key_file=tmp_path / "k"))
    await config.init()
    await config.put_model_settings(ModelSettings(backend="mock"))
    await config.put_inference_settings(InferenceSettings(interval_ms=100, width=320, height=180))
    rt = EdgeRuntime(config, SqliteEventStore(db))
    await rt.start()
    try:
        yield rt
    finally:
        await rt.stop()


async def _wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


async def test_synthetic_camera_streams_and_mock_infers(runtime: EdgeRuntime) -> None:
    cam = await runtime.config.create_camera(CameraIn(name="Demo", profile="synthetic"))
    await runtime.refresh_camera(cam.id)
    session = runtime.session(cam.id)
    assert isinstance(session, SyntheticCameraSession)
    assert await _wait(lambda: session.stats.frames_published >= 3)
    assert session.stats.state == "streaming"
    assert await _wait(lambda: cam.id in runtime.last_results)
    result = runtime.last_results[cam.id]
    assert result.metadata["status"] == "ok"
    assert result.model_id == "mock"
    status = runtime.status()
    assert status["cameras"][0]["camera_id"] == cam.id
    assert status["cameras"][0]["fps"] > 0


async def test_model_outage_does_not_stop_video(runtime: EdgeRuntime) -> None:
    cam = await runtime.config.create_camera(CameraIn(name="Demo", profile="synthetic"))
    await runtime.refresh_camera(cam.id)
    runtime.model.configure(ModelSettings(backend="vllm", model="m", endpoint="http://localhost:1"))
    runtime.model._adapter = BrokenAdapter()
    session = runtime.session(cam.id)
    assert await _wait(
        lambda: runtime.last_results.get(cam.id) is not None
        and runtime.last_results[cam.id].metadata["status"] == "inference_unavailable"
    )
    before = session.stats.frames_published
    await asyncio.sleep(0.5)
    assert session.stats.frames_published > before  # video kept flowing
    assert runtime.model.state == "unavailable"
    assert "pw@" not in (runtime.model.last_error or "")
    # No fabricated events while the model is down.
    assert runtime.events.count_events(cam.id) == 0


async def test_pack_events_reach_store_and_hot_rebinding(runtime: EdgeRuntime) -> None:
    cam = await runtime.config.create_camera(CameraIn(name="Demo", profile="synthetic"))
    await runtime.refresh_camera(cam.id)
    runtime.model._adapter = PersonAdapter()
    # No bindings yet: no events.
    assert await _wait(lambda: cam.id in runtime.last_results)
    assert runtime.events.count_events(cam.id) == 0
    await runtime.config.replace_bindings(
        cam.id,
        [{"pack_id": "moving_object", "parameters": {"min_observations": 1},
          "report_interval_seconds": 2}],
    )
    await runtime.refresh_bindings(cam.id)
    assert await _wait(lambda: runtime.events.count_events(cam.id) >= 1)
    events = runtime.events.list_events(camera_id=cam.id)
    assert events[0]["event_type"] == "person_activity"
    assert events[0]["pack_id"] == "moving_object"
    assert events[0]["track_id"].startswith("t")
    assert events[0]["has_frame"] is True
    assert runtime.events.frame_path(events[0]["event_id"]) is not None
    # Live result carries detections with stable track ids for the overlay.
    result = runtime.last_results[cam.id]
    assert result.metadata["detections"][0]["bbox"][0] == pytest.approx(0.45, abs=0.01)


async def test_disable_and_delete_stop_sessions(runtime: EdgeRuntime) -> None:
    cam = await runtime.config.create_camera(CameraIn(name="Demo", profile="synthetic"))
    await runtime.refresh_camera(cam.id)
    assert runtime.session(cam.id) is not None
    await runtime.config.set_camera_enabled(cam.id, False)
    await runtime.refresh_camera(cam.id)
    assert runtime.session(cam.id) is None
    await runtime.config.set_camera_enabled(cam.id, True)
    await runtime.refresh_camera(cam.id)
    assert runtime.session(cam.id) is not None
    await runtime.remove_camera(cam.id)
    assert runtime.session(cam.id) is None and cam.id not in runtime.last_results


async def test_default_model_is_chosen_from_host_on_first_start(tmp_path) -> None:
    db = str(tmp_path / "rt2.sqlite")
    config = ConfigStore(db, secrets=SecretBox(key_file=tmp_path / "k2"))
    rt = EdgeRuntime(config, SqliteEventStore(db))
    await rt.start()
    try:
        stored = await config.get_model_settings()
        assert stored.backend in {"vllm", "ollama", "mock"}
        assert rt.model.settings.backend == stored.backend
    finally:
        await rt.stop()
