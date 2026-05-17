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

All adapters implement `DetectionAdapter.infer(frame) -> frame`.
`MockDetectionAdapter` is the default and has zero model dependencies.
Do not add real model dependencies to the default install path — put them in `[vision]` extras.

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
