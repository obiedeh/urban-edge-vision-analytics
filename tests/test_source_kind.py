"""``source_kind`` on cameras, live results, events and evidence frames."""
from __future__ import annotations

import asyncio
import io
import shutil
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.main import app
from store.config_store import ConfigStore
from store.event_store import SqliteEventStore
from store.models import CameraIn, InferenceSettings, ModelSettings, UploadRecord
from store.secrets import SecretBox
from tests.test_runtime import PersonAdapter
from vision.camera_profiles import CAMERA_PROFILES, SOURCE_KINDS, source_kind_for
from vision.evidence_label import evidence_note, stamp_evidence
from vision.runtime import EdgeRuntime
from vision.uploads import probe_video_file, sha256_of

client = TestClient(app)


def test_every_profile_maps_to_a_known_source_kind() -> None:
    kinds = {p: source_kind_for(p) for p in CAMERA_PROFILES}
    assert set(kinds.values()) <= set(SOURCE_KINDS)
    assert kinds["tapo"] == kinds["generic_rtsp"] == kinds["http_mjpeg"] == "live_rtsp"
    assert kinds["rtsp_url"] == "live_rtsp"
    assert kinds["usb"] == "usb" and kinds["browser_webrtc"] == "browser"
    assert kinds["synthetic"] == "synthetic"
    assert source_kind_for("uploaded_video", "recorded") == "uploaded_recorded"
    assert source_kind_for("uploaded_video", "generated") == "uploaded_generated"
    assert source_kind_for("uploaded_video") == "uploaded_recorded"


def test_evidence_is_stamped_for_non_live_sources_only() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (320, 180), (40, 40, 40)).save(buf, format="JPEG")
    jpeg = buf.getvalue()
    assert stamp_evidence(jpeg, "live_rtsp") == jpeg
    assert stamp_evidence(jpeg, None) == jpeg
    stamped = stamp_evidence(jpeg, "uploaded_generated")
    assert stamped != jpeg
    top = Image.open(io.BytesIO(stamped)).crop((0, 0, 320, 8)).convert("RGB")
    assert max(top.tobytes()) > 60  # banner is visibly drawn over the dark frame
    assert evidence_note("synthetic") and evidence_note("usb") is None


def test_ingested_events_carry_source_kind() -> None:
    base = {"camera_id": "cam-ingest", "event_type": "vehicle_detected", "severity": "info"}
    with_kind = client.post("/events", json={**base, "source_kind": "usb"}).json()
    without = client.post("/events", json=base).json()
    assert client.get(f"/events/{with_kind['event_id']}").json()["source_kind"] == "usb"
    assert client.get(f"/events/{without['event_id']}").json()["source_kind"] is None


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


async def _wait(predicate, timeout=6.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


async def _bind_person_pack(rt: EdgeRuntime, camera_id: str) -> None:
    rt.model._adapter = PersonAdapter()
    await rt.config.replace_bindings(
        camera_id,
        [{"pack_id": "moving_object", "parameters": {"min_observations": 1},
          "report_interval_seconds": 2}],
    )
    await rt.refresh_bindings(camera_id)


async def test_synthetic_events_and_results_are_labelled(runtime: EdgeRuntime) -> None:
    cam = await runtime.config.create_camera(CameraIn(name="Demo", profile="synthetic"))
    await runtime.refresh_camera(cam.id)
    await _bind_person_pack(runtime, cam.id)
    assert await _wait(lambda: runtime.events.count_events(cam.id) >= 1)
    event = runtime.events.list_events(camera_id=cam.id)[0]
    assert event["source_kind"] == "synthetic"
    assert "not a live camera" in event["metadata"]["evidence_note"]
    assert runtime.events.frame_path(event["event_id"]) is not None
    assert await _wait(lambda: cam.id in runtime.last_results)
    assert runtime.last_results[cam.id].metadata["source_kind"] == "synthetic"
    assert runtime.status()["cameras"][0]["source_kind"] == "synthetic"


async def test_uploaded_generated_footage_is_labelled(runtime: EdgeRuntime, make_mp4) -> None:
    path = make_mp4(frames=50, fps=25)
    runtime.config.upload_dir.mkdir(parents=True, exist_ok=True)
    stored = runtime.config.upload_dir / "clip-abc.mp4"
    shutil.copy(path, stored)
    info = probe_video_file(stored)
    await runtime.config.add_upload(UploadRecord(
        id="clip-abc", filename="clip.mp4", stored_name=stored.name, content_type="video/mp4",
        size_bytes=stored.stat().st_size, sha256=sha256_of(stored), source_kind="generated",
        **info.to_dict(),
    ))
    cam = await runtime.config.create_camera(
        CameraIn(name="Replay", profile="uploaded_video", upload_id="clip-abc", playback="loop")
    )
    assert cam.source_kind == "uploaded_generated" and cam.upload is not None
    await runtime.refresh_camera(cam.id)
    await _bind_person_pack(runtime, cam.id)
    assert await _wait(lambda: runtime.events.count_events(cam.id) >= 1)
    event = runtime.events.list_events(camera_id=cam.id)[0]
    assert event["source_kind"] == "uploaded_generated"
    assert event["metadata"]["evidence_note"].startswith("GENERATED FOOTAGE")
    frame = runtime.events.frame_path(event["event_id"])
    assert frame is not None and frame.stat().st_size > 0
    session = runtime.session(cam.id)
    assert session is not None and session.kind == "file"
    assert runtime.status()["cameras"][0]["source_kind"] == "uploaded_generated"


async def test_live_camera_results_are_not_stamped(runtime: EdgeRuntime) -> None:
    cam = await runtime.config.create_camera(
        CameraIn(name="Browser", profile="browser_webrtc")
    )
    await runtime.refresh_camera(cam.id)
    push = runtime.push_session(cam.id)
    assert push is not None
    push.push_image(Image.new("RGB", (320, 180), (10, 10, 10)))
    await _bind_person_pack(runtime, cam.id)
    assert await _wait(lambda: runtime.events.count_events(cam.id) >= 1)
    event = runtime.events.list_events(camera_id=cam.id)[0]
    assert event["source_kind"] == "browser"
    assert "evidence_note" not in event["metadata"]
