# Urban Edge Vision Analytics

**Status: Functional. Under active field validation and tuning on live cameras.**

Edge vision analytics for streets and intersections. Network cameras are configured in a web UI, video plays live in the browser, a vision-language model inspects frames on its own cadence, and use-case packs turn what the model sees into structured traffic events that an operator reviews.

This is operational analysis with a human in the loop. It is not automated enforcement, and it does not read license plates.

**Project overview:** [open the one-page showcase](https://obiedeh.github.io/urban-edge-vision-analytics/docs/showcase/) for the pack diagrams, the signal path and screens from the running console. Source: [`docs/showcase/index.html`](docs/showcase/index.html); it is a single self-contained file, so it also opens straight from a clone.

## Editions

This repository is the open core: camera setup in the UI, live video decoupled from inference, model selection with a memory preflight, the four use-case packs and operator review.

**Urban Edge Pro** is developed privately on top of this core. It adds video feed connectors (RTSP links, USB cameras, browser and phone cameras, and uploaded footage) with a source label on every frame and event, plus upload and playback controls on the Live view. [See Urban Edge Pro](https://obiedeh.github.io/urban-edge-vision-analytics-pro.html). Source available on request.

---

## What it does today

Every item below is implemented on `main` and covered by the test suite or by code you can read at the linked path. Nothing here is a performance claim; see [Not yet measured](#not-yet-measured). For a picture of where each pack sits on a street, see the [site plan in the showcase](https://obiedeh.github.io/urban-edge-vision-analytics/docs/showcase/#plan-h).

**Camera setup in the UI**
- Vendor profiles with main and sub stream paths filled in automatically: Tapo, Hikvision, Dahua, Amcrest, Axis, Reolink, UniFi Protect, generic RTSP, HTTP MJPEG, browser webcam (WebRTC), plus a labelled synthetic feed for demos and tests (`vision/camera_profiles.py`).
- Add, edit, enable, disable and delete cameras without editing files or restarting. Configuration lives in SQLite (`store/config_store.py`).
- Test connection opens the stream, decodes one frame and returns a thumbnail, or a classified error: unreachable, authentication failed, wrong path, codec, timeout (`vision/probe.py`).
- Credentials are encrypted at rest with a key file kept outside the repository (`store/secrets.py`). The API never returns a stored password. Stored passwords are only reused for the host and port they were saved for. Credentials are masked in URLs, logs, errors and status payloads (`vision/redaction.py`).

**Multiple cameras, packs per camera**
- Any number of cameras can be saved; each enabled camera runs its own capture and inference loop.
- Use-case packs are selected per camera, and one camera can run several packs at once. The only combination refused is speed and stop-sign on the same camera, because they need different sight lines (`packs/compatibility.py`).

**Live video decoupled from inference**
- Each camera is decoded at its native frame rate into a latest-frame slot and streamed to the browser as MJPEG (`vision/camera_engine.py`, `api/routes/stream.py`).
- Inference samples that slot on its own interval. The model server is not in the video path: when the model is unavailable the Live page keeps playing and shows "inference unavailable" instead of inventing events (`vision/runtime.py`, `tests/test_runtime.py`).

**Model selection by environment, with memory preflight**
- On first start the app picks a default for the host: Cosmos-Reason2-2B served by vLLM on Jetson AGX Thor, Gemma 4 on a workstation with an RTX 5090 class GPU (`vision/host_capabilities.py`). The operator can change it in the Models page.
- One adapter talks to any vision endpoint that serves the chat-completions API: vLLM, Ollama or NVIDIA NIM. Backend, endpoint and model are editable and switch live.
- The model catalog is checked against the host: free VRAM on a discrete GPU, available RAM on Jetson unified memory. Models that will not fit are shown as blocked with the reason.
- On Jetson the app can launch NVIDIA's vLLM container itself. That container keeps running across API restarts, and stopping it requires an explicit, logged confirmation because it may be shared with another app on the device.

**Use-case packs** (`packs/`)
- **Stop sign:** a vehicle track entering the drawn stop zone is watched until it leaves, then classified as full stop, rolling stop or no stop from its dwell time and minimum tracked speed in the zone.
- **Speed between two gates:** speed is computed from the time a track takes to cross gate A then gate B and the real-world distance entered for them. Only measured crossings produce events.
- **Moving object:** tracked people (or other chosen classes), with direction, optionally limited to a zone.
- **Vehicle count:** each tracked vehicle is counted once when it crosses the drawn count line, by direction and class (car, truck, bus, motorcycle). Counts are stored in SQLite with per-camera totals and an hourly breakdown. Count records never enter the review queue.
- Zones, gates and the count line are drawn in the Studio page on a snapshot from the camera. Coordinates are stored normalised, so they survive resolution changes.
- A simple frame-to-frame tracker gives detections stable ids (`packs/tracking.py`).

**Operator review**
- Events are stored in SQLite and survive restarts. Events a pack flags for review appear in the Review queue with the frame the model saw at that moment.
- The operator confirms or dismisses each item and can attach a ground-truth note describing a known pass (for example "my car, full stop"). Run artifacts list pack output beside those notes; no accuracy figure is computed automatically.

**Deployment**
- A systemd user unit runs the API and UI as a service with a persistent log (`deploy/urban-edge.service`).
- `telemetry/run_capture.py` records a measured live run from a running instance: video frame rate and drops, inference latency percentiles, events, board power from `tegrastats`. It refuses to start if the model server is not ready, aborts if the server goes down mid-run, and never starts or stops a model server itself.

---

## Architecture

The same path with a short description of each stage is in the [showcase](https://obiedeh.github.io/urban-edge-vision-analytics/docs/showcase/#flow-h).

```text
 camera (RTSP / HTTP MJPEG / browser webcam)
        |
        v
 capture thread per camera  ->  latest-frame slot  ->  MJPEG to the Live page
                                      |
                                      v  (sampled every inference interval)
                               vision-language model
                               (vLLM, Ollama or NIM endpoint)
                                      |
                                      v
                        tracker  ->  packs bound to the camera
                                      |
                                      v
                 SQLite: events, vehicle counts, review status
                                      |
                                      v
             operator UI: Live, Cameras, Models, Studio, Events, Review
```

Repository layout:

```text
api/          FastAPI application, routes, model server launcher
vision/       camera profiles, probe, capture sessions, model runtime, redaction
store/        SQLite config store, event store, secret encryption
packs/        stop sign, speed, moving object, vehicle count, tracker, geometry
events/       event and incident schemas
telemetry/    metrics, run capture
cloud/        optional edge-to-cloud publishers (off by default)
web/          operator UI (Vite, React, TypeScript)
deploy/       systemd unit
docs/         design notes; showcase/ holds the one-page project overview
tests/        unit, API and runtime tests
```

---

## Quick start

```bash
git clone https://github.com/obiedeh/urban-edge-vision-analytics.git
cd urban-edge-vision-analytics
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cd web && pnpm install && pnpm build && cd ..
uvicorn api.main:app --port 8080
```

Open `http://localhost:8080`, go to Cameras, add a camera, press Test connection, save. Pick or load a model in Models. Draw zones and choose packs in Studio. Watch Live and work the Review queue.

No camera to hand: add one with the "Synthetic test feed" profile and select the mock backend in Models. The UI labels both as synthetic.

Settings that are not in the UI are in [`.env.example`](.env.example): where the SQLite store and the encryption key file live. Never commit either.

Run as a service on the device:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/urban-edge.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now urban-edge
```

---

## Tests

```bash
make install-dev
make verify        # ruff, mypy, pytest
cd web && pnpm build
```

CI runs lint, type checks, the Python tests and the web build on every push to `main`. The tests cover camera create, update, delete and enable; the connection probe and its error classes; credential encryption and redaction; model switching and the memory preflight; the tracker and all four packs, including double-count prevention and direction for the vehicle count; several packs on one camera; the review queue and ground-truth notes; and an end-to-end runtime test in which video keeps flowing while the model is down.

---

## Not yet measured

The system runs end to end, but none of the following has a committed measurement yet. Treat any number you see elsewhere as unverified until an artifact under `artifacts/` backs it.

- **Live-camera latency and power on the Jetson AGX Thor.** No live-camera run has been committed. Per-frame inference latency, video frame rate under load and board power are unknown.
- **Pack accuracy against known passes.** Stop-sign, speed, moving-object and vehicle-count output has not been compared with ground truth. The Review page can record known passes; the comparison has not been run.
- **Speed calibration error.** The two-gate speed depends on the entered distance, the gate placement and the inference interval. Its error has not been characterised.
- **Long-run stability.** Behaviour over hours or days (reconnects, memory, store growth) has not been measured.

Also not established: detection quality of the vision-language models on real street scenes, behaviour at night or in bad weather, and tracker identity stability in dense traffic.

---

## Planned upgrades

Not built yet:

- Live-camera evidence runs on the Thor, committed under `artifacts/`
- Ground-truth validation of the speed and stop-sign packs
- Recorded-video summarization (NVIDIA VSS)
- AWS edge-to-cloud sync. A publisher interface and a local file publisher exist and are tested, and an IoT Core publisher is implemented against a fake client only; nothing has been run against AWS. Design notes: [docs/cloud-architecture.md](docs/cloud-architecture.md)
- Wrong-way detection
- Illegal parking
- Pedestrian counts and yield
- Queue length
- Near-miss detection
- Red-light running

There will be no license plate reading.

---

## Scope

This project is for operational analysis and infrastructure research with operator review. It is not intended for autonomous legal enforcement or automated ticketing.

License: Apache 2.0.
