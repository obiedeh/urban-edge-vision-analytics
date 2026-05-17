# Architecture

```text
Camera / Video Source
        |
        v
  Source Loader  ->  Detection Adapter  ->  Flow Analytics  ->  Event Store
        |                   |                     |                  |
   (synthetic,          (Mock / ONNX /       (FlowWindow,       (TrafficEvent,
    video file,          TensorRT /            congestion,        Incident,
    RTSP stream)         NIM endpoint)         class counts)      operator review)
                                                                      |
                                                                      v
                                                               FastAPI Backend
                                                          (events, incidents, metrics)
```

## Source Loader

`vision/source_loader.py` yields `InferenceFrame` records. Current source:

- `synthetic_frames` — deterministic synthetic frames for dev/test

Planned sources:

- `VideoFileSource` — OpenCV-backed video file replay
- `RtspSource` — live RTSP stream ingestion
- `MockReplaySource` — recorded frame replay with timestamps

## Detection Adapter

`vision/adapters.py` defines `DetectionAdapter`, a single-method interface:

```python
def infer(self, frame: InferenceFrame) -> InferenceFrame
```

Current adapter:

- `MockDetectionAdapter` — seeded random detections, zero dependencies

Planned adapters:

- `OnnxDetectionAdapter` — YOLO/RT-DETR via ONNX Runtime (CPU + GPU)
- `TensorRTAdapter` — TensorRT engine inference for Jetson Orin
- `NimDetectionAdapter` — NVIDIA NIM OpenAI-compatible detection endpoint

## Flow Analytics

`analytics/flow.py` maintains a sliding `FlowWindow` per camera:

- vehicle count from latest frame
- congestion threshold crossing
- mean inference latency across window
- per-class vehicle counts

`analytics/metrics.py` tracks aggregate pipeline metrics across the session.

## Event Store

`events/lifecycle.py` manages in-memory `TrafficEvent` and `IntersectionIncident` state.

Events carry severity, event type, track IDs, confidence, and operator review flags.

Incidents group related events for operator review with status lifecycle:
`open` → `under_review` → `resolved` / `dismissed`

## FastAPI Backend

`api/main.py` exposes:

- `GET /health` — liveness check
- `GET /runtime` — uptime, camera count, event count, incident count
- `GET /metrics/inference` — latency p95/p99, sample count, dropped frames
- `POST /events` — ingest a traffic event
- `GET /events` — list events (filterable by camera_id)
- `GET /events/{id}` — get single event
- `POST /incidents` — open an incident from events
- `GET /incidents` — list incidents (filterable by status)
- `PATCH /incidents/{id}` — update incident status and operator notes

## Telemetry

`telemetry/metrics.py` — inference latency tracking with p95/p99

`telemetry/runtime.py` — uptime, camera count, event count snapshot
