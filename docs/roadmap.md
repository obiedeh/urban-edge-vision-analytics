# Production Roadmap

## Phase 1 — Runnable Skeleton (current)

- Pydantic schemas for frames, detections, events, and incidents
- Mock detection adapter (seeded random, zero model dependencies)
- Synthetic frame source for dev and test
- Flow analytics: sliding window vehicle count, congestion detection, class counts
- Inference latency telemetry with p95/p99
- FastAPI backend: event ingestion, incident management, runtime metrics
- Test suite: schemas, flow analytics, event lifecycle, API smoke

## Phase 2 — Real Detection

- ONNX Runtime adapter for YOLOv8n or RT-DETR-nano
- OpenCV-backed video file source
- Benchmark report: model vs mock latency, throughput at 10 FPS
- Docker image build and local run verification

## Phase 3 — Jetson Deployment

- TensorRT engine adapter for Jetson Orin
- RTSP source for live camera ingestion
- Jetson-specific config (`configs/jetson.json`) validated on hardware
- Latency benchmarks: CPU vs TensorRT, memory footprint, sustained runtime
- `docker compose` deployment profile for Jetson

## Phase 4 — Operator Workflows

Authoritative spec: [`docs/operator-wrapper-brief.md`](operator-wrapper-brief.md).
Implementation handoff: [`docs/claude-code-kickoff.md`](claude-code-kickoff.md).

Phase 4 scope locked to three use case packs + compatibility rule +
configurable report interval + honest Metrics & KPIs dashboard, in three
commits. Items below are explicitly deferred to a future phase:

- Multimodal incident summarization via local VLM or NVIDIA NIM
- Incident export and PDF/CSV reports
- Prometheus metrics endpoint and Grafana dashboard profile
- Schedules / alert routing / webhook channels
- Multi-role auth (RBAC) and login
