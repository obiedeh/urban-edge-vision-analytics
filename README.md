# Urban Edge Vision Analytics

Edge vision inference and traffic event observability for smart intersections.

This project turns camera frames, vehicle detections, and flow analytics into structured traffic events that an operator can review. The goal is not automated enforcement. The goal is infrastructure intelligence with human-reviewed incident management.

---

## What Works Now

This repository includes a runnable production-grade skeleton:

- Pydantic schemas for inference frames, vehicle detections, traffic events, and incidents
- Mock detection adapter — seeded, deterministic, zero model dependencies
- Synthetic frame source for development and testing
- Sliding flow window analytics: vehicle count, congestion detection, per-class counts
- Inference latency telemetry with p95/p99 tracking
- FastAPI backend: event ingestion, incident lifecycle, runtime metrics
- Operator incident workflow: open → under_review → resolved / dismissed
- Configs for local dev and Jetson Orin deployment
- Test suite: schemas, flow analytics, event lifecycle, API smoke

---

## Architecture

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

---

## Repository Layout

```text
api/          FastAPI application and routes
vision/       Frame schemas, detection adapter interface, source loaders
events/       Traffic event and incident schemas, event store lifecycle
analytics/    Flow window analytics, congestion detection, pipeline metrics
telemetry/    Inference latency metrics, runtime snapshot
configs/      Local and Jetson JSON configs
examples/     Sample payloads
docs/         Architecture and roadmap
tests/        Unit and smoke tests
```

---

## Quick Start

```bash
cd projects/urban-edge-vision-analytics
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn api.main:app --reload --port 8080
```

Open:

- API health: `http://127.0.0.1:8080/health`
- OpenAPI docs: `http://127.0.0.1:8080/docs`
- Inference metrics: `http://127.0.0.1:8080/metrics/inference`
- Runtime snapshot: `http://127.0.0.1:8080/runtime`

---

## Docker

```bash
docker build -t urban-edge-vision .
docker run -p 8080:8080 urban-edge-vision
```

---

## Traffic Event Model

Events carry:

- camera ID and timestamp
- event type: `vehicle_detected`, `red_light_violation`, `unsafe_turn`, `congestion_onset`, `congestion_clear`, `wrong_way`
- severity: `info`, `warning`, `critical`
- vehicle count and track IDs
- confidence score
- operator review recommendation
- inference latency and metadata

See `examples/sample_event.json`.

---

## Detection Adapter Strategy

The current detection adapter is intentionally mocked. That is not a weakness — it is the correct engineering position at this stage.

Real adapters target the same `DetectionAdapter` interface:

- **ONNX Runtime** — YOLOv8n or RT-DETR-nano, CPU + CUDA
- **TensorRT** — Jetson Orin optimized engine
- **NVIDIA NIM** — hosted detection endpoint via OpenAI-compatible API

Install vision extras when a real model is available:

```bash
pip install -e .[vision]
```

Do not hardwire inference to one backend. Keep adapters replaceable.

---

## Deployment Paths

Local dev (mock adapter):

```bash
uvicorn api.main:app --reload --port 8080
```

Jetson Orin (ONNX adapter):

```bash
DETECTION_ADAPTER=onnx uvicorn api.main:app --host 0.0.0.0 --port 8080
```

---

## Tests

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest
```

---

## Production Roadmap

1. Add ONNX Runtime adapter (YOLOv8n / RT-DETR-nano) and video file source
2. Benchmark detection latency and throughput on CPU vs GPU
3. Add TensorRT adapter and validate on Jetson Orin hardware
4. Add RTSP source for live camera ingestion
5. Add evidence packaging (frame crops, detection overlays, metadata bundle)
6. Add multimodal incident summarization via local VLM or NVIDIA NIM
7. Add Prometheus metrics endpoint and Grafana deployment profile
8. Add operator review UI or REST-driven review workflow

---

## Positioning

This project supports a broader engineering focus around:

- Edge AI inference
- Physical AI observability
- smart-city traffic analytics
- multimodal AI systems
- Jetson Orin deployment
- operator-facing infrastructure intelligence

---

## Important Note

This project is for operational analysis and infrastructure research.

It is not intended for autonomous legal enforcement or fully automated ticketing systems.
All critical events are flagged for operator review.
