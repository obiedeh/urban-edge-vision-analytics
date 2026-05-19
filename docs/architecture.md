# Architecture

## System Purpose

This repository is the applied edge vision intelligence layer in the portfolio. It converts frame sources, mock or future model detections, and flow analytics into traffic events, incidents, metrics, and human-reviewed infrastructure evidence.

## Current Implementation Status

- **Implemented:** FastAPI backend, Pydantic schemas, deterministic mock detection adapter, synthetic frame source, flow analytics, incident lifecycle, telemetry metrics, tests, and mock report generation.
- **Mock validation path:** synthetic frames and mock detections prove the event, flow, telemetry, and reporting path.
- **Planned Jetson deployment:** ONNX Runtime adapter, TensorRT adapter, RTSP source, and Jetson benchmark artifact.
- **Future hardware validation:** real camera/video samples and sustained edge runtime evidence.

## Main Components

- `vision/`: frame schemas, source loading, and detection adapter interface.
- `analytics/`: flow window analytics and congestion summaries.
- `events/`: traffic event and incident lifecycle models.
- `api/`: FastAPI routes for events, incidents, metrics, and runtime snapshots.
- `telemetry/`: latency and runtime metric helpers.
- `examples/`: mock inference report and sample payloads.
- `docs/diagrams/`: Mermaid architecture views for reviewer inspection.

## Runtime Flow

The current runnable path uses deterministic synthetic frames and the mock detection adapter. The pipeline converts detections into flow analytics and events, stores incidents, exposes runtime metrics, and can generate a mock evidence report.

## Data / Telemetry Flow

Frame metadata becomes detections. Detections become vehicle counts, congestion signals, traffic events, and incident state. Latency metrics and mock report artifacts summarize the run. Mock outputs do not prove real camera accuracy.

## Deployment Modes

- **Local development:** FastAPI, synthetic frame source, mock adapter, tests, and mock report generation.
- **Planned model adapter mode:** OpenCV video source and ONNX Runtime detector.
- **Planned Jetson deployment:** TensorRT adapter, RTSP source, runtime metrics, and benchmark artifact.
- **Future operator review:** human-reviewed infrastructure intelligence, not automated enforcement.

## Evidence Artifacts

- Existing mock report: `examples/mock_inference_report.json`.
- Reviewer placeholders: `artifacts/sample-inputs/`, `artifacts/sample-outputs/`, `artifacts/logs/`, and `artifacts/reports/`.
- Diagram sources: `docs/diagrams/`.

## Known Limitations

- The mock detector does not prove real model accuracy.
- The repo does not claim real traffic-camera deployment.
- Jetson performance remains planned until benchmark artifacts are committed.

## Next Validation Step

Add one reproducible sample-video pipeline artifact with an ONNX adapter plan, runtime metrics, limitations, and reviewable output.
