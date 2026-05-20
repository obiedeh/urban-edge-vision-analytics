from analytics.flow import FlowWindow
from vision.adapters import MockDetectionAdapter, NvidiaVssAdapter
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


def test_build_detection_adapter_selects_mock():
    assert isinstance(build_detection_adapter("mock"), MockDetectionAdapter)


def test_build_detection_adapter_selects_nvidia_vss():
    adapter = build_detection_adapter("nvidia-vss", endpoint="https://nvidia.example/vss")
    assert isinstance(adapter, NvidiaVssAdapter)


def test_build_detection_adapter_defaults_to_local_cosmos():
    adapter = build_detection_adapter("nvidia-cosmos")
    assert adapter.config.endpoint == "http://127.0.0.1:8000/v1"
    assert adapter.config.model == "nvidia/cosmos-reason2-2b"


def test_frame_to_event_payload_marks_congestion():
    frame = InferenceFrame(
        frame_id="frame-1",
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
                frame_id="frame-1",
                timestamp_ms=1000,
            )
        ],
    )
    window = FlowWindow(camera_id="tapo-1", congestion_threshold=1)
    window.push(frame)

    payload = frame_to_event_payload(frame, window)

    assert payload["camera_id"] == "tapo-1"
    assert payload["event_type"] == "congestion_onset"
    assert payload["severity"] == "warning"
    assert payload["vehicle_count"] == 1
    assert payload["metadata"]["source_type"] == "rtsp"
