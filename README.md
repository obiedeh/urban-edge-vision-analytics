# Urban Edge Vision Analytics

Edge vision inference and traffic event observability for smart intersections.

This project turns camera frames, vehicle detections, and flow analytics into structured traffic events that an operator can review. The goal is not automated enforcement. The goal is infrastructure intelligence with human-reviewed incident management.

---

## Core Stack

**Implemented:** Python · FastAPI · Pydantic · mock detection adapter · synthetic frame source · flow analytics · Pytest

**Planned / integration path:** OpenCV · ONNX Runtime · TensorRT · RTSP source · Jetson benchmark artifact

<p>
  <img src="https://img.shields.io/badge/Python-3.x-blue" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-API-009688" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Pydantic-schemas-E92063" alt="Pydantic" />
  <img src="https://img.shields.io/badge/OpenCV-integration%20path-5C3EE8" alt="OpenCV integration path" />
  <img src="https://img.shields.io/badge/ONNX%20Runtime-planned-005CED" alt="ONNX Runtime planned" />
  <img src="https://img.shields.io/badge/TensorRT-planned-76B900" alt="TensorRT planned" />
  <img src="https://img.shields.io/badge/Pytest-tested-brightgreen" alt="Pytest" />
</p>

---

## Architecture and Evidence

- [Architecture overview](docs/architecture.md)
- [System architecture diagram](docs/diagrams/system-architecture.mmd)
- [Runtime flow diagram](docs/diagrams/runtime-flow.mmd)
- [Data flow diagram](docs/diagrams/data-flow.mmd)
- [Deployment view diagram](docs/diagrams/deployment-view.mmd)
- [Sample outputs](artifacts/sample-outputs/)
- [Logs](artifacts/logs/)
- [Reports](artifacts/reports/)

---

## Recommended GitHub About

- **Suggested short description:** Edge vision intelligence system for infrastructure events using frame analysis, operational summaries, and edge deployment patterns.
- **Suggested topics/tags:** `edge-ai`, `computer-vision`, `infrastructure`, `video-analytics`, `operational-ai`, `event-detection`
- **Positioning category:** Core

---

## What Works Now

This repository includes a runnable engineering scaffold:

- Pydantic schemas for inference frames, vehicle detections, traffic events, and incidents
- Mock detection adapter — seeded, deterministic, zero model dependencies
- Synthetic frame source for development and testing
- Sliding flow window analytics: vehicle count, congestion detection, per-class counts
- Inference latency telemetry with p95/p99 tracking
- FastAPI backend: event ingestion, incident lifecycle, runtime metrics
- Operator incident workflow: open → under_review → resolved / dismissed
- Configs for local dev and Jetson Orin deployment planning
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

Primary target today: Linux local development with the deterministic mock adapter. Jetson Orin is a planned deployment target after ONNX or TensorRT adapters are implemented and benchmarked.

```bash
git clone https://github.com/obiedeh/urban-edge-vision-analytics.git
cd urban-edge-vision-analytics
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

Planned real adapters target the same `DetectionAdapter` interface:

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

Jetson Orin target path after ONNX adapter implementation:

```bash
DETECTION_ADAPTER=onnx uvicorn api.main:app --host 0.0.0.0 --port 8080
```

Do not treat the Jetson command as validated until a real ONNX adapter, model file, and benchmark artifact are committed.

---

## Tests

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest
```

For the Linux validation path used by CI:

```bash
make install-dev
make verify
```

The current CI gate runs Ruff linting, type checks, and tests on Ubuntu.

## Mock Evidence Artifact

Generate deterministic synthetic evidence from the mock detection adapter:

```bash
python examples/generate_mock_report.py --output examples/mock_inference_report.json
```

The generated report is committed at `examples/mock_inference_report.json`. It proves the current mock-frame pipeline executes and summarizes detections, class counts, and congestion windows. It does not claim real camera accuracy, Jetson latency, or automated enforcement readiness.

For the reviewer-facing deliverables checklist, see [PORTFOLIO_DELIVERABLES.md](PORTFOLIO_DELIVERABLES.md).

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
