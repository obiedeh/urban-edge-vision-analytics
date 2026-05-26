# AGENTS.md — Urban Edge Vision Analytics

## Purpose

Edge vision inference and traffic event observability for smart intersections.
Operator-reviewed incident management, not automated enforcement.

## Stack

- Python 3.11+
- FastAPI + Pydantic v2
- ONNX Runtime / TensorRT (optional, Phase 2+)
- OpenCV (optional, Phase 2+)
- pytest + ruff

## Package Layout

```
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

## Detection Adapters

All adapters implement `DetectionAdapter.infer(frame, prompt: str) -> frame`.
`MockDetectionAdapter` is the default and has zero model dependencies.

**Live runtime selector is locked to exactly three values:** `cosmos-2b`,
`cosmos-8b`, `vss`. Other adapter classes (`OllamaAdapter`,
`NvidiaNimAdapter`, `MockDetectionAdapter`) remain importable for dev/test
but are **not** in `build_detection_adapter`'s selector branch.

`vss` is **batch-only**; it does not appear in the live UI model menu.
Use it via the `summarize-recording` CLI / `POST /recordings/{id}/summarize` API.

## Live Engine Architecture

- **Transport:** WebRTC via `aiortc` (NOT server-side FFmpeg subprocess). FFmpeg subprocess use is reserved for **writing** rotating MP4 recordings — never for reading live frames.
- **Loops:** display loop and inference loop are **decoupled** via `FrameSlot` (asyncio.Queue maxsize=1, overwrite-on-put). Inference latency must never block display.
- **Results:** stream from inference loop to frontend via SSE (`sse-starlette`).
- **Backend:** vLLM is the only live-inference backend. Default endpoint `http://localhost:8000/v1`, default model `nvidia/Cosmos-Reason2-2B`.

Full spec: `docs/live-vlm-engine-brief.md`.

## Coding Rules

- All schemas use Pydantic v2 `BaseModel`
- No global mutable state outside `api/main.py` module-level singletons
- No OpenCV or ONNX imports in core event/analytics/telemetry modules
- `operator_review_recommended=True` must be set on any event with severity `critical`
- Do not implement autonomous enforcement logic — observability and operator review only

## Testing

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest
```

Tests must pass without optional extras installed.
Mock adapter is the test default — never require a real model in CI.

## Running Locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
uvicorn api.main:app --reload --port 8080
```

API docs: http://127.0.0.1:8080/docs
