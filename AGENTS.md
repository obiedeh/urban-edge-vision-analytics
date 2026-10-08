# AGENTS.md: Urban Edge Vision Analytics

## Purpose

Edge vision inference and traffic event observability for smart intersections.
Operator-reviewed incident management, not automated enforcement.

## Stack

- Python 3.11+
- FastAPI + Pydantic v2, aiosqlite/sqlite3
- PyAV (libav) for camera decode, Pillow for JPEG, cryptography (Fernet) for secrets
- aiortc for browser-webcam ingress
- Vite + React + TypeScript + Tailwind operator UI in `web/`
- pytest + ruff + mypy

## Package Layout

```
api/          FastAPI application, routes, managed vLLM launcher,
              optional TLS front door (tls_proxy, local_cert)
vision/       Camera profiles and connectors (rtsp_url, usb_devices, uploads),
              probe, PyAV camera sessions, model runtime, EdgeRuntime
              (per-camera inference loops), adapters, redaction, evidence labels
store/        SQLite config store (cameras, uploads, settings, bindings, zones),
              SQLite event store, Fernet secrets
packs/        Use-case packs (stop sign, speed, moving object), tracker,
              geometry, PackRunner
events/       Traffic event and incident schemas, debounce reporter
analytics/    Flow window analytics
telemetry/    Inference latency metrics, runtime snapshot, telemetry contract
cloud/        Edge-to-cloud publishers (null, file, IoT Core); off by default
web/          Operator UI (Live, Cameras, Models, Studio, Events, Review)
configs/      Cloud-publisher JSON configs only; cameras live in SQLite
artifacts/    Committed measured runs (see README)
tests/        Unit, API and runtime tests
```

## Runtime Configuration

Nothing operational is hardcoded. Cameras (vendor profile, host, port,
credentials, stream path/quality, enabled, packs, zones; or a pasted RTSP
link, a USB device and mode, or an uploaded video and its playback), the model backend
(vLLM / Ollama / NIM / mock, endpoint, model) and inference settings
(interval, resolution, prompt preset) are edited in the web UI, stored in the
SQLite config store (`STORE_PATH`), and applied to the running process by
`vision.runtime.EdgeRuntime` without a restart. Passwords and API keys are
Fernet-encrypted (`store/secrets.py`); the key lives outside the repo. The API
never returns a stored secret; `vision/redaction.py` masks credentials in
URLs, logs, errors and status payloads. `configs/camera.local.json` is a
legacy file imported once and then ignored.

## Detection Adapters

All adapters implement `DetectionAdapter.infer(frame, prompt: str) -> frame`.
`OpenAIVisionAdapter` talks to any OpenAI-compatible `/v1/chat/completions`
server that accepts images (vLLM serving Cosmos-Reason2 or Gemma 4, Ollama,
NVIDIA NIM). `MockDetectionAdapter` is the test default. The environment
default on first start is Cosmos-Reason2-2B via vLLM on Jetson and Gemma 4 via
Ollama on a GPU workstation; the operator can change it in Models.

Bounding boxes are normalised to the unit square after inference
(`normalize_detections_to_unit`); zones, gates and pack geometry use the same
0..1 space.

## Live Engine Architecture

- **Capture:** one `StreamCameraSession` thread per enabled camera decodes the
  RTSP/RTSPS/HTTP stream with PyAV at native rate into a latest-frame slot
  (`vision/camera_engine.py`); `UsbCameraSession` does the same for a V4L2
  device and `FileCameraSession` plays an uploaded video at its own frame
  rate, looped or once. Browser cameras arrive through aiortc into a
  `PushCameraSession`. Synthetic sessions exist for tests and demos and are
  labelled as such.
- **Provenance:** every camera has a `source_kind` (`live_rtsp`, `usb`,
  `browser`, `uploaded_recorded`, `uploaded_generated`, `synthetic`). The
  runtime stamps it on inference results and events; evidence frames from
  non-live sources get a visible banner (`vision/evidence_label.py`).
- **Display:** `GET /stream/{id}/live.mjpeg` streams the slot to the browser;
  the model server is never in this path.
- **Inference:** one asyncio task per camera samples the slot on
  `inference.interval_ms`, resizes to the configured resolution and calls the
  shared `ModelRuntime`. Failures surface as `inference_unavailable`; no event
  is fabricated.
- **Packs:** `PackRunner` tracks detections across frames and runs the bound
  packs with the stored zones/gates; events are persisted to SQLite and
  flagged for the review queue.
- **Results:** SSE `GET /live/results` (sse-starlette).
- **VSS record→summarize:** not implemented; planned. Nothing in the UI
  refers to it.

## Coding Rules

- All schemas use Pydantic v2 `BaseModel`
- No global mutable state outside `api/main.py` module-level singletons
- No OpenCV or ONNX imports in core event/analytics/telemetry modules
- `operator_review_recommended=True` must be set on any event with severity `critical`
- Do not implement autonomous enforcement logic; observability and operator review only
- Schema changes are additive: new columns get defaults in `_CAMERA_COLUMNS`, new
  tables use `CREATE TABLE IF NOT EXISTS`; `tests/test_store_upgrade.py` must keep passing
- Uploads, certificates and keys live outside the repository and are gitignored

## Testing

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest
```

Tests must pass without optional extras installed.
Mock adapter is the test default; never require a real model in CI.

## Running Locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
uvicorn api.main:app --reload --port 8080
```

API docs: http://127.0.0.1:8080/docs
