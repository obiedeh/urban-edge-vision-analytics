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
    OllamaAdapter,
    VllmAdapter,
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

    # ── Local adapters (no auth, no endpoint required) ────────────────────────
    if normalized == "mock":
        return MockDetectionAdapter()

    if normalized in {"ollama"}:
        # Default: http://localhost:11434/v1  (Ollama OpenAI-compat endpoint)
        return OllamaAdapter(
            endpoint=endpoint or os.getenv("OLLAMA_ENDPOINT") or None,
            model=model or os.getenv("OLLAMA_MODEL") or None,
        )

    if normalized in {"vllm"}:
        # Default: http://localhost:8000/v1  (vLLM OpenAI-compat endpoint)
        return VllmAdapter(
            endpoint=endpoint or os.getenv("VLLM_ENDPOINT") or None,
            model=model or os.getenv("VLLM_MODEL") or None,
        )

    # ── NVIDIA cloud / on-prem adapters (require endpoint) ────────────────────
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
        "Unsupported detector adapter. "
        "Use: mock, ollama, vllm, nvidia-nim, nvidia-vss, nvidia-cosmos."
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


def _make_annotated_jpeg(frame: InferenceFrame, vehicle_count: int) -> bytes | None:
    """Generate a HUD-style annotated JPEG for the snapshot transport.

    Used when no real camera frame is available (synthetic mode or raw-RGB mode).
    Returns None if PIL is not installed.
    """
    try:
        import io
        from datetime import UTC, datetime

        from PIL import Image, ImageDraw

        W, H = frame.width, frame.height
        img = Image.new("RGB", (W, H), (12, 18, 28))
        draw = ImageDraw.Draw(img)

        # Subtle grid lines
        for x in range(0, W, 64):
            draw.line([(x, 0), (x, H)], fill=(22, 34, 50), width=1)
        for y in range(0, H, 64):
            draw.line([(0, y), (W, y)], fill=(22, 34, 50), width=1)

        # HUD corner brackets
        blen = 18
        for cx, cy, sx, sy in [
            (8, 8, 1, 1), (W - 8, 8, -1, 1),
            (8, H - 8, 1, -1), (W - 8, H - 8, -1, -1),
        ]:
            draw.line([(cx, cy), (cx + sx * blen, cy)], fill=(0, 190, 100), width=2)
            draw.line([(cx, cy), (cx, cy + sy * blen)], fill=(0, 190, 100), width=2)

        # Animated scan line (moves with wall-clock time)
        scan_y = int(frame.timestamp_ms / 12) % H
        for step in range(4):
            y = (scan_y - step) % H
            draw.line([(0, y), (W, y)], fill=(0, min(255, 50 + step * 50), 40 + step * 15), width=1)

        # Bounding boxes from inference detections
        _COLORS: dict[str, tuple[int, int, int]] = {
            "car":        (0, 220, 100),
            "truck":      (0, 180, 255),
            "bus":        (255, 180, 0),
            "motorcycle": (220, 80, 255),
            "pedestrian": (255, 100, 80),
            "cyclist":    (80, 200, 255),
            "unknown":    (180, 180, 180),
        }
        for det in frame.detections:
            bb = det.bounding_box
            x1, y1 = int(bb.x), int(bb.y)
            x2, y2 = int(bb.x + bb.width), int(bb.y + bb.height)
            color = _COLORS.get(str(det.vehicle_class).lower(), (180, 180, 180))
            draw.rectangle([(x1, y1), (x2, y2)], outline=color, width=2)
            draw.text(
                (x1 + 3, max(0, y1 - 11)),
                f"{det.vehicle_class} {det.bounding_box.confidence:.0%}",
                fill=color,
            )

        # Centre info panel
        ts = datetime.fromtimestamp(frame.timestamp_ms / 1000, tz=UTC).strftime("%H:%M:%S UTC")
        cx, cy = W // 2, H // 2
        draw.rectangle([(cx - 108, cy - 44), (cx + 108, cy + 64)], fill=(6, 10, 18), outline=(30, 50, 70))
        draw.text((cx, cy - 28), frame.camera_id,         fill=(200, 205, 215), anchor="mm")
        draw.text((cx, cy - 8),  "◉  SYNTHETIC  FEED",   fill=(0, 220, 90),   anchor="mm")
        draw.text((cx, cy + 16), f"Vehicles: {vehicle_count}", fill=(150, 215, 155), anchor="mm")
        draw.text((cx, cy + 44), ts,                      fill=(100, 105, 140), anchor="mm")

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82)
        return buf.getvalue()
    except Exception:
        return None


def frame_to_event_payload(
    frame: InferenceFrame,
    window: FlowWindow,
    was_congested: bool = False,
) -> dict:
    vehicle_count = window.vehicle_count
    congested = window.is_congested
    has_detections = len(frame.detections) > 0

    if congested:
        event_type = EventType.congestion_onset
        severity = Severity.warning
        operator_review_recommended = True
    elif was_congested:
        event_type = EventType.congestion_clear
        severity = Severity.info
        operator_review_recommended = False
    elif has_detections:
        event_type = EventType.vehicle_detected
        severity = Severity.info
        operator_review_recommended = False
    else:
        # Nothing moving in frame (excluding background motion like trees)
        event_type = EventType.scene_clear
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


def iter_synthetic_frames(
    camera_id: str,
    settings: LivePipelineSettings,
):
    """Generate synthetic InferenceFrame objects at the configured rate.

    Used when the mock adapter is active and no real RTSP camera is available.
    Allows the full event pipeline to run without ffmpeg or a camera connection.
    """
    frame_interval = 1.0 / max(settings.sample_fps, 0.1)
    frames_read = 0
    while settings.max_frames is None or frames_read < settings.max_frames:
        yield InferenceFrame(
            frame_id=str(uuid.uuid4()),
            camera_id=camera_id,
            timestamp_ms=int(time.time() * 1000),
            width=settings.width,
            height=settings.height,
            source_type="synthetic",
            metadata={"synthetic": True},
        )
        frames_read += 1
        time.sleep(frame_interval)


def run_live_pipeline(
    connection: CameraConnection,
    settings: LivePipelineSettings,
    detector: DetectionAdapter | None = None,
    synthetic: bool = False,
) -> int:
    detector = detector or MockDetectionAdapter()
    window = FlowWindow(
        camera_id=connection.camera_id,
        window_size=settings.flow_window_size,
        congestion_threshold=settings.congestion_threshold,
    )
    event_count = 0
    was_congested = False
    was_detecting = False          # were there detections last frame?
    last_scene_clear_at: float = 0.0
    # Re-announce a quiet scene at most once per this interval (seconds)
    SCENE_CLEAR_REPOST_S = 30.0
    events_url = f"{settings.api_url.rstrip('/')}/events"

    frame_source = (
        iter_synthetic_frames(connection.camera_id, settings)
        if synthetic
        else iter_rtsp_frames(connection, settings)
    )

    snapshot_url = f"{settings.api_url.rstrip('/')}/stream/{connection.camera_id}/snapshot.jpg"

    with httpx.Client(timeout=10.0) as client:
        for frame in frame_source:
            inferred = detector.infer(frame)
            window.push(inferred)

            # ── Push snapshot frame to in-process transport via HTTP ──────────
            jpeg: bytes | None = (
                inferred.frame_bytes  # real MJPEG frame
                or _make_annotated_jpeg(inferred, window.vehicle_count)  # synthetic / raw
            )
            if jpeg:
                try:
                    client.post(
                        snapshot_url,
                        content=jpeg,
                        headers={"Content-Type": "image/jpeg"},
                        timeout=2.0,
                    )
                except Exception:
                    pass  # snapshot failure must never stop event pipeline

            # ── Event gate: only post when something meaningful changed ────────
            has_detections = len(inferred.detections) > 0
            currently_congested = window.is_congested
            now_ts = time.time()

            # Post if:
            #   • congestion is active or just cleared
            #   • objects are in the frame right now
            #   • just transitioned from detecting → quiet (post scene_clear once)
            #   • scene has been quiet a while and we haven't reminded recently
            should_post = (
                currently_congested
                or was_congested
                or has_detections
                or (was_detecting and not has_detections)  # transition → quiet
                or (not has_detections and (now_ts - last_scene_clear_at) >= SCENE_CLEAR_REPOST_S)
            )

            if should_post:
                payload = frame_to_event_payload(inferred, window, was_congested=was_congested)
                if not has_detections and not currently_congested:
                    last_scene_clear_at = now_ts
                was_congested = currently_congested
                response = client.post(events_url, json=payload)
                response.raise_for_status()
                event_count += 1
                print(
                    "posted_event "
                    f"camera_id={inferred.camera_id} "
                    f"vehicle_count={window.vehicle_count} "
                    f"event_type={response.json().get('event_type')}"
                    f"{' [synthetic]' if synthetic else ''}",
                    flush=True,
                )
            else:
                was_congested = currently_congested

            was_detecting = has_detections

    return event_count



def main() -> None:
    import argparse as _ap

    parser = _ap.ArgumentParser(
        description="Sample a camera feed (real or synthetic) and post vision events to the API.",
        formatter_class=_ap.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", required=True, help="Path to camera JSON config.")
    parser.add_argument("--api-url", default="http://127.0.0.1:8080")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    parser.add_argument("--sample-fps", type=float, default=1.0)
    parser.add_argument(
        "--frames", type=int, default=0,
        help="Max frames to process (0 = run forever).",
    )
    parser.add_argument("--congestion-threshold", type=int, default=10)
    parser.add_argument("--flow-window-size", type=int, default=30)
    parser.add_argument(
        "--detector",
        default=os.getenv("DETECTION_ADAPTER", "mock"),
        choices=["mock", "ollama", "vllm", "nvidia-nim", "nvidia-vss", "nvidia-cosmos"],
    )
    parser.add_argument("--detector-endpoint", default=os.getenv("NVIDIA_VISION_ENDPOINT"))
    parser.add_argument("--detector-model", default=os.getenv("NVIDIA_VISION_MODEL"))
    parser.add_argument(
        "--synthetic", action="store_true",
        help="Generate synthetic frames (no camera / ffmpeg required). "
             "Auto-enabled for mock adapter when ffmpeg is absent.",
    )
    args = parser.parse_args()

    # 0 frames → run forever
    max_frames: int | None = args.frames if args.frames > 0 else None

    # Auto-enable synthetic when using mock and ffmpeg not installed
    use_synthetic = args.synthetic or (
        args.detector == "mock" and shutil.which("ffmpeg") is None
    )

    from vision.camera_profiles import build_camera_connection, load_camera_config

    config = load_camera_config(args.config)
    if use_synthetic:
        # Build the connection without strict credential validation
        try:
            connection = build_camera_connection(config)
        except Exception:
            # No credentials in config — create a minimal stub for camera_id
            camera_id = str(config.get("camera_id", "mock-camera"))
            connection = CameraConnection(
                camera_id=camera_id,
                model_type=str(config.get("model_type", "generic_rtsp")),
                host=str(config.get("host", "localhost")),
                feed_url="rtsp://localhost/synthetic",
                ffplay_command=[],
            )
    else:
        connection = verify_camera_connection(args.config, require_ffplay=False)

    settings = LivePipelineSettings(
        width=args.width,
        height=args.height,
        sample_fps=args.sample_fps,
        max_frames=max_frames,
        congestion_threshold=args.congestion_threshold,
        flow_window_size=args.flow_window_size,
        api_url=args.api_url,
        # Always use MJPEG for real cameras so frame bytes are available for
        # the snapshot transport.  Synthetic mode never calls ffmpeg so the
        # format field has no effect there.
        frame_format="raw" if use_synthetic else "mjpeg",
    )

    print(f"camera_id={connection.camera_id}", flush=True)
    print(f"model_type={connection.model_type}", flush=True)
    print(f"detector={args.detector}", flush=True)
    print(f"synthetic={use_synthetic}", flush=True)
    if not use_synthetic:
        print(f"feed_url={connection.masked_feed_url}", flush=True)

    detector = build_detection_adapter(
        args.detector,
        endpoint=args.detector_endpoint,
        model=args.detector_model,
    )
    count = run_live_pipeline(connection, settings, detector=detector, synthetic=use_synthetic)
    print(f"processed_events={count}", flush=True)


if __name__ == "__main__":
    main()
