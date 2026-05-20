from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass

import httpx

from analytics.flow import FlowWindow
from events.schemas import EventType, Severity
from vision.adapters import (
    DetectionAdapter,
    MockDetectionAdapter,
    NvidiaCosmosAdapter,
    NvidiaEndpointConfig,
    NvidiaNimAdapter,
    NvidiaVssAdapter,
)
from vision.camera_profiles import CameraConnection, verify_camera_connection
from vision.schemas import InferenceFrame


@dataclass(frozen=True)
class LivePipelineSettings:
    width: int = 640
    height: int = 360
    sample_fps: float = 1.0
    max_frames: int | None = None
    congestion_threshold: int = 10
    flow_window_size: int = 30
    api_url: str = "http://127.0.0.1:8080"
    frame_format: str = "raw"


def build_detection_adapter(
    adapter_name: str,
    endpoint: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> DetectionAdapter:
    normalized = adapter_name.strip().lower().replace("_", "-")
    if normalized == "mock":
        return MockDetectionAdapter()

    api_key = api_key or os.getenv("NVIDIA_API_KEY")
    if normalized in {"nvidia-cosmos", "cosmos", "world-model"}:
        endpoint = endpoint or os.getenv("NVIDIA_VISION_ENDPOINT") or "http://127.0.0.1:8000/v1"
        model = model or os.getenv("NVIDIA_VISION_MODEL") or "nvidia/cosmos-reason2-2b"
    else:
        endpoint = endpoint or os.getenv("NVIDIA_VISION_ENDPOINT")
        model = model or os.getenv("NVIDIA_VISION_MODEL")
    if not endpoint:
        raise ValueError(
            f"{adapter_name} requires --detector-endpoint or NVIDIA_VISION_ENDPOINT."
        )

    config = NvidiaEndpointConfig(endpoint=endpoint, api_key=api_key, model=model)
    if normalized in {"nvidia-nim", "nim"}:
        return NvidiaNimAdapter(config)
    if normalized in {"nvidia-vss", "vss"}:
        return NvidiaVssAdapter(config)
    if normalized in {"nvidia-cosmos", "cosmos", "world-model"}:
        return NvidiaCosmosAdapter(config)

    raise ValueError(
        "Unsupported detector adapter. Use mock, nvidia-nim, nvidia-vss, or nvidia-cosmos."
    )


def build_ffmpeg_frame_command(
    connection: CameraConnection,
    settings: LivePipelineSettings,
) -> list[str]:
    base = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-i",
        connection.feed_url,
        "-vf",
        f"fps={settings.sample_fps},scale={settings.width}:{settings.height}",
    ]
    if settings.frame_format == "mjpeg":
        return base + ["-vcodec", "mjpeg", "-f", "image2pipe", "pipe:1"]
    return base + ["-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]


def _read_jpeg_frame(stream) -> bytes:
    buffer = bytearray()
    started = False
    previous = None
    while True:
        chunk = stream.read(1)
        if not chunk:
            return b""
        byte = chunk[0]
        if not started:
            if previous == 0xFF and byte == 0xD8:
                buffer.extend([0xFF, 0xD8])
                started = True
            previous = byte
            continue
        buffer.append(byte)
        if previous == 0xFF and byte == 0xD9:
            return bytes(buffer)
        previous = byte


def iter_rtsp_frames(
    connection: CameraConnection,
    settings: LivePipelineSettings,
):
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg was not found on PATH. Install ffmpeg to read camera frames.")
    command = build_ffmpeg_frame_command(connection, settings)
    frame_size = settings.width * settings.height * 3
    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    try:
        if process.stdout is None:
            raise RuntimeError("ffmpeg stdout pipe was not opened.")
        frames_read = 0
        while settings.max_frames is None or frames_read < settings.max_frames:
            if settings.frame_format == "mjpeg":
                payload = _read_jpeg_frame(process.stdout)
            else:
                payload = process.stdout.read(frame_size)
                if len(payload) != frame_size:
                    break
            if not payload:
                break
            frames_read += 1
            yield InferenceFrame(
                frame_id=str(uuid.uuid4()),
                camera_id=connection.camera_id,
                timestamp_ms=int(time.time() * 1000),
                width=settings.width,
                height=settings.height,
                source_type="rtsp",
                metadata={"video_url": connection.feed_url},
                frame_bytes=payload if settings.frame_format == "mjpeg" else None,
            )
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()


def frame_to_event_payload(
    frame: InferenceFrame,
    window: FlowWindow,
    was_congested: bool = False,
) -> dict:
    vehicle_count = window.vehicle_count
    congested = window.is_congested
    if congested:
        event_type = EventType.congestion_onset
        severity = Severity.warning
        operator_review_recommended = True
    elif was_congested:
        event_type = EventType.congestion_clear
        severity = Severity.info
        operator_review_recommended = False
    else:
        event_type = EventType.vehicle_detected
        severity = Severity.info
        operator_review_recommended = False

    return {
        "camera_id": frame.camera_id,
        "event_type": event_type.value,
        "severity": severity.value,
        "vehicle_count": vehicle_count,
        "track_ids": [d.track_id for d in frame.detections],
        "confidence": max((d.bounding_box.confidence for d in frame.detections), default=1.0),
        "operator_review_recommended": operator_review_recommended,
        "inference_latency_ms": frame.inference_latency_ms,
        "metadata": {
            "source_type": frame.source_type,
            "frame_id": frame.frame_id,
            "class_counts": window.class_counts(),
            "mean_inference_latency_ms": window.mean_inference_latency_ms,
        },
    }


def run_live_pipeline(
    connection: CameraConnection,
    settings: LivePipelineSettings,
    detector: DetectionAdapter | None = None,
) -> int:
    detector = detector or MockDetectionAdapter()
    window = FlowWindow(
        camera_id=connection.camera_id,
        window_size=settings.flow_window_size,
        congestion_threshold=settings.congestion_threshold,
    )
    event_count = 0
    was_congested = False
    events_url = f"{settings.api_url.rstrip('/')}/events"
    with httpx.Client(timeout=10.0) as client:
        for frame in iter_rtsp_frames(connection, settings):
            inferred = detector.infer(frame)
            window.push(inferred)
            payload = frame_to_event_payload(inferred, window, was_congested=was_congested)
            was_congested = window.is_congested
            response = client.post(events_url, json=payload)
            response.raise_for_status()
            event_count += 1
            print(
                "posted_event "
                f"camera_id={inferred.camera_id} "
                f"vehicle_count={window.vehicle_count} "
                f"event_type={response.json().get('event_type')}"
            )
    return event_count


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sample a real RTSP camera feed and post vision events to the API.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", required=True, help="Path to camera JSON config.")
    parser.add_argument("--api-url", default="http://127.0.0.1:8080", help="FastAPI base URL.")
    parser.add_argument("--width", type=int, default=640, help="Sampled frame width.")
    parser.add_argument("--height", type=int, default=360, help="Sampled frame height.")
    parser.add_argument("--sample-fps", type=float, default=1.0, help="Sample rate from RTSP feed.")
    parser.add_argument("--frames", type=int, default=10, help="Number of frames to process.")
    parser.add_argument("--congestion-threshold", type=int, default=10)
    parser.add_argument("--flow-window-size", type=int, default=30)
    parser.add_argument(
        "--detector",
        default=os.getenv("DETECTION_ADAPTER", "mock"),
        choices=["mock", "nvidia-nim", "nvidia-vss", "nvidia-cosmos"],
        help="Inference adapter for sampled frames.",
    )
    parser.add_argument(
        "--detector-endpoint",
        default=os.getenv("NVIDIA_VISION_ENDPOINT"),
        help="NVIDIA service endpoint for non-mock adapters.",
    )
    parser.add_argument(
        "--detector-model",
        default=os.getenv("NVIDIA_VISION_MODEL"),
        help="Model or service profile name for non-mock adapters.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    connection = verify_camera_connection(args.config, require_ffplay=False)
    settings = LivePipelineSettings(
        width=args.width,
        height=args.height,
        sample_fps=args.sample_fps,
        max_frames=args.frames,
        congestion_threshold=args.congestion_threshold,
        flow_window_size=args.flow_window_size,
        api_url=args.api_url,
        frame_format="mjpeg" if args.detector == "nvidia-cosmos" else "raw",
    )
    print(f"camera_id={connection.camera_id}")
    print(f"model_type={connection.model_type}")
    print(f"feed_url={connection.masked_feed_url}")
    print(f"detector={args.detector}")
    detector = build_detection_adapter(
        args.detector,
        endpoint=args.detector_endpoint,
        model=args.detector_model,
    )
    print(f"processed_events={run_live_pipeline(connection, settings, detector=detector)}")


if __name__ == "__main__":
    main()
