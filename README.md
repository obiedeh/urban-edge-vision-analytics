# Urban Edge Vision Analytics

**Status: Functional. Under active field validation and tuning on live cameras.**

Edge vision analytics for streets and intersections. Network cameras are configured in a web UI, video plays live in the browser, a vision-language model inspects frames on its own cadence, and use-case packs turn what the model sees into structured traffic events that an operator reviews.

This is operational analysis with a human in the loop. It is not automated enforcement, and it does not read license plates.

**Project overview:** [open the one-page showcase](https://obiedeh.github.io/urban-edge-vision-analytics/docs/showcase/) for the pack diagrams, the signal path and screens from the running console. Source: [`docs/showcase/index.html`](docs/showcase/index.html); it is a single self-contained file, so it also opens straight from a clone.

---

## What it does today

Every item below is implemented on `main` and covered by the test suite or by code you can read at the linked path. Nothing here is a performance claim; see [Not yet measured](#not-yet-measured). For a picture of where each pack sits on a street, see the [site plan in the showcase](https://obiedeh.github.io/urban-edge-vision-analytics/docs/showcase/#plan-h).

**Camera setup in the UI**
- Vendor profiles with main and sub stream paths filled in automatically: Tapo, Hikvision, Dahua, Amcrest, Axis, Reolink, UniFi Protect, generic RTSP and HTTP MJPEG (`vision/camera_profiles.py`).
- Add, edit, enable, disable and delete cameras without editing files or restarting. Configuration lives in SQLite (`store/config_store.py`).
- Test connection opens the stream, decodes one frame and returns a thumbnail, or a classified error: unreachable, authentication failed, wrong path, codec, timeout, device missing or busy (`vision/probe.py`).
- Credentials are encrypted at rest with a key file kept outside the repository (`store/secrets.py`). The API never returns a stored password. Stored passwords are only reused for the host and port they were saved for. Credentials are masked in URLs, logs, errors and status payloads (`vision/redaction.py`).

**Video feed connectors** (all on the Cameras page, same packs and review flow as a network camera)
- **RTSP URL.** Paste a complete `rtsp://` or `rtsps://` link, with optional username and password fields. Credentials embedded in the link are taken out, stored encrypted like any camera password, and the link is saved, shown and logged without them (`vision/rtsp_url.py`). Works with no credentials at all.
- **USB camera.** `GET /cameras/usb-devices` lists the `/dev/video*` capture devices with their names and the sizes and frame rates they support (read with the V4L2 ioctls, no extra tools); the operator picks the device, resolution and rate. Capture runs through the same PyAV path as network streams (`vision/usb_devices.py`, `UsbCameraSession` in `vision/camera_engine.py`). A missing, busy or unreadable device reports a plain-language error.
- **Uploaded video.** Upload an MP4, MOV or MKV with the **Upload video** button on the Cameras page (size limit configurable with `URBAN_EDGE_UPLOAD_MAX_BYTES`, default 2 GB). Files are stored outside the repository next to the SQLite store and play at their native frame rate, looped or once; deleting an upload removes the file (`vision/uploads.py`, `FileCameraSession`). At upload time the operator declares whether the footage is **recorded** or **generated**, and that label follows every frame.
- **Browser camera (computer or phone).** The Live page shares the browser's camera over WebRTC with a camera picker: front or back on phones, a device list on laptops. Browsers only allow this on `localhost` or over HTTPS; the page says so and names the URL to use. See [Browser camera from another device](#browser-camera-from-another-device) for the optional HTTPS front door.
- **Source labelling.** Every camera, live result, event and run artifact records `source_kind`: `live_rtsp`, `usb`, `browser`, `uploaded_recorded`, `uploaded_generated` or `synthetic`. Events and evidence frames from uploaded or synthetic sources carry a visible "not a live camera" label on Live, Events, Review and in `run.json` (`vision/evidence_label.py`).

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
api/          FastAPI application, routes, model server launcher, optional TLS front door
vision/       camera profiles, RTSP link parsing, USB devices, uploads, probe,
              capture sessions, model runtime, redaction, evidence labels
store/        SQLite config store (cameras, uploads), event store, secret encryption
packs/        stop sign, speed, moving object, vehicle count, tracker, geometry
events/       event and incident schemas
telemetry/    metrics, run capture
cloud/        optional edge-to-cloud publishers (off by default)
web/          operator UI (Vite, React, TypeScript)
deploy/       systemd units (API, optional HTTPS front door)
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

No network camera to hand: plug in a USB camera and pick the "USB camera" profile, upload a clip with the "Upload video" button, share your laptop camera with "Browser camera", or add a "Synthetic test feed" and select the mock backend in Models. Everything that is not a live camera is labelled as such on screen and in the data.

### Browser camera from another device

Browsers expose the camera only in a secure context: `http://localhost` on the device itself, or HTTPS anywhere else. To share a phone's or another computer's camera, enable the optional HTTPS front door. It adds an HTTPS listener on port 8443 that relays to the unchanged HTTP API on 8080, so every existing `http://` URL keeps working.

```bash
# 1. A local certificate for the names and addresses you open the console at
.venv/bin/python -m api.local_cert 192.0.2.10 thor.local      # writes ~/.config/urban-edge/tls/{cert,key}.pem
#    or, if you prefer a locally trusted CA:  mkcert -install && mkcert -cert-file cert.pem -key-file key.pem 192.0.2.10 thor.local

# 2. Run the front door (opt-in)
.venv/bin/python -m api.tls_proxy      # https://0.0.0.0:8443 -> http://127.0.0.1:8080
#    as a service: cp deploy/urban-edge-tls.service ~/.config/systemd/user/ && systemctl --user enable --now urban-edge-tls
```

Then open `https://192.0.2.10:8443/` on the phone, accept or install the certificate once, and press **Share camera** on the Live page. Certificates and keys live under `~/.config/urban-edge/tls/` and are ignored by git. Set `URBAN_EDGE_TLS_LISTEN`, `URBAN_EDGE_TLS_TARGET`, `URBAN_EDGE_TLS_CERT` and `URBAN_EDGE_TLS_KEY` to change ports or paths.

Settings that are not in the UI are in [`.env.example`](.env.example): where the SQLite store, the uploaded videos and the encryption key file live, the upload size limit, and the TLS front door. Never commit any of them.

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

CI runs lint, type checks, the Python tests and the web build on every push to `main`. The tests cover camera create, update, delete and enable; the connection probe and its error classes; credential encryption and redaction; RTSP link parsing and credential stripping, including that a pasted link is never echoed or stored with its password; USB device listing against a mocked device tree and the busy/missing wording; upload validation, the size limit, loop and play-once playback at native rate; `source_kind` on live results, events and evidence; a config database written by the previous release upgrading with its cameras unchanged; the TLS front door; model switching and the memory preflight; the tracker and all four packs, including double-count prevention and direction for the vehicle count; several packs on one camera; the review queue and ground-truth notes; and an end-to-end runtime test in which video keeps flowing while the model is down.

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
