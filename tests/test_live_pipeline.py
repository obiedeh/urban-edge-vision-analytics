import pytest

from analytics.flow import FlowWindow
from vision.adapters import NvidiaCosmosAdapter, NvidiaVssAdapter
from vision.camera_profiles import build_camera_connection
from vision.live_pipeline import (
    LivePipelineSettings,
    build_detection_adapter,
    build_ffmpeg_frame_command,
    frame_to_event_payload,
)
from vision.schemas import BoundingBox, InferenceFrame, VehicleClass, VehicleDetection


def test_build_ffmpeg_frame_command_wraps_tapo_rtsp(monkeypatch):
    monkeypatch.setenv("CAMERA_USERNAME", "test-user")
    monkeypatch.setenv("CAMERA_PASSWORD", "test-password")
    connection = build_camera_connection(
        {
            "model_type": "tapo",
            "host": "192.168.1.50",
            "stream": "1",
            "username_env": "CAMERA_USERNAME",
            "password_env": "CAMERA_PASSWORD",
        }
    )

    command = build_ffmpeg_frame_command(connection, LivePipelineSettings())

    assert command[:6] == ["ffmpeg", "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp"]
    assert "rtsp://test-user:test-password@192.168.1.50:554/stream1" in command
    assert "fps=1.0,scale=640:360" in command


def test_build_ffmpeg_frame_command_can_output_mjpeg(monkeypatch):
    monkeypatch.setenv("CAMERA_USERNAME", "test-user")
    monkeypatch.setenv("CAMERA_PASSWORD", "test-password")
    connection = build_camera_connection(
        {
            "model_type": "tapo",
            "host": "192.168.1.50",
            "stream": "1",
            "username_env": "CAMERA_USERNAME",
            "password_env": "CAMERA_PASSWORD",
        }
    )

    command = build_ffmpeg_frame_command(connection, LivePipelineSettings(frame_format="mjpeg"))

    assert command[-5:] == ["-vcodec", "mjpeg", "-f", "image2pipe", "pipe:1"]


def test_build_detection_adapter_rejects_mock():
    # Live runtime selector is locked to {cosmos-2b, cosmos-8b, vss} per AD-3.
    # Mock stays as the test default but is not selectable at runtime.
    with pytest.raises(ValueError, match="Allowed: cosmos-2b, cosmos-8b, vss"):
        build_detection_adapter("mock")


def test_build_detection_adapter_rejects_legacy_ollama():
    with pytest.raises(ValueError, match="Allowed: cosmos-2b, cosmos-8b, vss"):
        build_detection_adapter("ollama")


def test_build_detection_adapter_selects_vss():
    adapter = build_detection_adapter("vss", endpoint="https://nvidia.example/vss")
    assert isinstance(adapter, NvidiaVssAdapter)


def test_build_detection_adapter_nvidia_vss_alias_still_works():
    adapter = build_detection_adapter("nvidia-vss", endpoint="https://nvidia.example/vss")
    assert isinstance(adapter, NvidiaVssAdapter)


def test_build_detection_adapter_defaults_cosmos_2b_to_vllm():
    adapter = build_detection_adapter("cosmos-2b")
    assert isinstance(adapter, NvidiaCosmosAdapter)
    assert adapter.config.endpoint == "http://localhost:8000/v1"
    assert adapter.config.model == "nvidia/Cosmos-Reason2-2B"


def test_build_detection_adapter_defaults_cosmos_8b_to_vllm():
    adapter = build_detection_adapter("cosmos-8b")
    assert isinstance(adapter, NvidiaCosmosAdapter)
    assert adapter.config.endpoint == "http://localhost:8000/v1"
    assert adapter.config.model == "nvidia/Cosmos-Reason2-8B"


def test_build_detection_adapter_cosmos_alias_resolves_to_2b():
    adapter = build_detection_adapter("nvidia-cosmos")
    assert isinstance(adapter, NvidiaCosmosAdapter)
    assert adapter.config.model == "nvidia/Cosmos-Reason2-2B"


def _car_frame(frame_id: str = "frame-1") -> InferenceFrame:
    return InferenceFrame(
        frame_id=frame_id,
        camera_id="tapo-1",
        timestamp_ms=1000,
        width=640,
        height=360,
        source_type="rtsp",
        inference_latency_ms=4.2,
        detections=[
            VehicleDetection(
                track_id="track-1",
                vehicle_class=VehicleClass.car,
                bounding_box=BoundingBox(x=0, y=0, width=10, height=10, confidence=0.8),
                frame_id=frame_id,
                timestamp_ms=1000,
            )
        ],
    )


def _empty_frame(frame_id: str = "frame-2") -> InferenceFrame:
    return InferenceFrame(
        frame_id=frame_id,
        camera_id="tapo-1",
        timestamp_ms=2000,
        width=640,
        height=360,
        source_type="rtsp",
    )


def test_frame_to_event_payload_marks_congestion():
    frame = _car_frame()
    window = FlowWindow(camera_id="tapo-1", congestion_threshold=1)
    window.push(frame)

    payload = frame_to_event_payload(frame, window)

    assert payload["camera_id"] == "tapo-1"
    assert payload["event_type"] == "congestion_onset"
    assert payload["severity"] == "warning"
    assert payload["vehicle_count"] == 1
    assert payload["metadata"]["source_type"] == "rtsp"


def test_frame_to_event_payload_emits_congestion_clear_on_transition():
    window = FlowWindow(camera_id="tapo-1", congestion_threshold=1)
    congested_frame = _car_frame("frame-1")
    clear_frame = _empty_frame("frame-2")
    window.push(congested_frame)
    assert window.is_congested

    window.push(clear_frame)
    assert not window.is_congested

    payload = frame_to_event_payload(clear_frame, window, was_congested=True)

    assert payload["event_type"] == "congestion_clear"
    assert payload["severity"] == "info"


def test_frame_to_event_payload_vehicle_detected_when_never_congested():
    window = FlowWindow(camera_id="tapo-1", congestion_threshold=10)
    frame = _car_frame()
    window.push(frame)

    payload = frame_to_event_payload(frame, window, was_congested=False)

    assert payload["event_type"] == "vehicle_detected"


def test_iter_rtsp_frames_raises_when_ffmpeg_missing(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _: None)
    from vision.camera_profiles import build_camera_connection
    from vision.live_pipeline import LivePipelineSettings, iter_rtsp_frames

    connection = build_camera_connection(
        {"model_type": "unifi_protect", "host": "192.168.1.1", "stream": "live"}
    )
    with pytest.raises(RuntimeError, match="ffmpeg was not found on PATH"):
        list(iter_rtsp_frames(connection, LivePipelineSettings()))
