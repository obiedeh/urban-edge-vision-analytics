# Portfolio Deliverables

This repository is scoped to operator-reviewed edge vision observability for smart-intersection workflows.

## One-Command Checks

```bash
make install-dev
make verify
```

CI validates Ruff linting, type checks, tests, mock evidence generation, and artifact existence on Ubuntu.

## Current Proof Artifacts

| Artifact | Purpose |
| --- | --- |
| `.github/workflows/ci.yml` | Ubuntu validation for install, lint, type check, tests, and artifact generation |
| `examples/mock_inference_report.json` | Deterministic synthetic-frame report from the mock detection adapter |
| `examples/sample_event.json` | Example structured traffic event payload |

## Current Evidence

- FastAPI app exposes health, runtime, inference metrics, event, and incident endpoints.
- Unit and smoke tests cover schemas, flow analytics, event lifecycle, and API behavior.
- Mock inference report processes 8 synthetic frames and emits 19 deterministic mock detections.
- Flow analytics reports class counts and congestion-window counts from the mock run.

## Credibility Boundary

This repo does not currently prove real camera accuracy, Jetson latency, TensorRT acceleration, or automated enforcement readiness.

The mock adapter is useful for validating data contracts, event flow, CI, and observability plumbing. Real-world credibility still requires a public sample-video path, a real model adapter, overlay/evidence images, and Jetson benchmark results.

## Next Evidence Targets

1. Add a reproducible public sample-video workflow.
2. Add an ONNX Runtime adapter with a documented model source.
3. Generate detection overlay images and metadata bundles.
4. Benchmark CPU and Jetson Orin latency with the same input clip.
