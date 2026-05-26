# Live VLM Engine — Implementation Brief

> **Status:** v1.0 — implementation-ready
> **Owner:** Obinna (obiedeh)
> **Targets:** RTX 5090 dev (primary) → Jetson Thor AGX prod (future)
> **Date:** 2026-05-25
> **Supersedes:** `docs/operator-wrapper-brief.md` §"Out of scope" exclusion of WebRTC transport. WebRTC is now in scope for the live-monitoring path; snapshot transport remains correct for the operator review path. Both coexist.

## Goal

Rebuild the live video + VLM inference engine so that:

1. **Video is smooth** (camera-native FPS in the browser, not 1 FPS slideshows)
2. **Inference runs independently** of display and never blocks it
3. **The model menu is exactly three options**: Cosmos-Reason2-2B, Cosmos-Reason2-8B, NVIDIA VSS endpoint
4. **vLLM is the only live-inference backend** (Ollama removed from the runtime selector)
5. **Recorded MP4 → VSS summarization** exists as a separate batch pipeline alongside live

The project keeps its unique value: structured `TrafficEvent` + operator review workflow + RTSP camera profiles + traffic-domain use case packs. We are **not forking** [nvidia-ai-iot/live-vlm-webui](https://github.com/nvidia-ai-iot/live-vlm-webui). We are adopting four of its patterns and writing them into this codebase.

## Hard rules (non-negotiable)

- **No autonomous enforcement.** Same rule as `AGENTS.md`. The VLM produces text and confidence; the operator decides.
- **Structured events stay.** Free-text VLM output enriches a `TrafficEvent` (in `vlm_summary`, `vlm_reasoning`, `vlm_model` fields). It does **not** replace `event_type`, `severity`, `vehicle_count`, or `track_id`.
- **No forking live-vlm-webui.** Lift patterns, write them into our codebase. No vendored copy. No git submodule.
- **vLLM is the only live backend.** `OllamaAdapter` class stays for dev/test imports but is **removed from `build_detection_adapter`'s selector**.
- **Mock adapter stays the test default.** Same rule as `AGENTS.md`. No CI test may require a real model or vLLM server.
- **No new top-level packages** beyond `vision/webrtc/`. WebRTC code lives under `vision/`. Inference loop lives under `vision/`. Recorder + summarizer live under `vision/`.
- **No commit trailers, no AI attribution, no co-author lines** in commits.

## Why this work is happening (root-cause diagnosis)

The current live pipeline (`vision/live_pipeline.py`) drags because:

1. `LivePipelineSettings.sample_fps: float = 1.0` and the FFmpeg command uses `fps={settings.sample_fps}` — FFmpeg drops the camera's native 30 FPS to 1 FPS *before* anything reaches Python. That is not lag, that is a slideshow by design.
2. The loop is serial: read frame → preprocess → HTTP inference call (200ms–2s) → event post → repeat. The next frame cannot be sampled until inference returns. Display is gated on inference latency.
3. There is no way for the user to change FPS, inference cadence, or resolution at runtime — all are CLI args.

Live-vlm-webui's selling point — *"smooth video while VLM processes frames in background"* — exists because it splits display from inference. We adopt that pattern.

## Architectural decisions

### AD-1: WebRTC transport via aiortc, replacing server-side FFmpeg pipe

**Decision:** Browser captures camera via `getUserMedia()`, streams to FastAPI server over WebRTC using [aiortc](https://github.com/aiortc/aiortc) (MIT, pure Python). Server receives decoded frames via `MediaStreamTrack.recv()`. FFmpeg-subprocess-as-source is **deprecated for live** (kept only for *recording* — see AD-5).

**Why:**
- Eliminates FFmpeg subprocess + pipe overhead on the live path
- Browser handles encoding/network at native FPS, server gets decoded frames at line rate
- This is exactly how `live-vlm-webui` solves the same problem
- aiortc is well-maintained, MIT licensed, and Python-native (no C++ deps beyond PyAV)

**Library choices (locked):**
- `aiortc` — WebRTC peer connection
- `av` (PyAV) — codec; pulled in transitively by aiortc but pin it for clarity

**RTSP cameras (camera_profiles):** Stay supported via a server-side bridge. RTSP feed → ffmpeg → in-process frame source → published over the same `MediaStreamTrack`-equivalent path. Implementation detail: same `FrameSlot` (AD-2) accepts frames from either WebRTC or RTSP-bridge source.

### AD-2: Dual-loop architecture (display loop ≠ inference loop)

**Decision:** Three concurrent async loops, decoupled via a shared `FrameSlot`:

```
[Display loop]   WebRTC track  ──► FrameSlot (asyncio.Queue maxsize=1, overwrite-on-put)
                                       │
                                       ├──► (display always sees latest frame; browser handles render)
                                       │
[Inference loop] sampler @ inference_interval_ms ──► reads FrameSlot ──► active adapter.infer()
                                       │                                       │
                                       │                                       ▼
                                       │                                  TrafficEvent + vlm fields
                                       │                                       │
[Result loop]    SSE stream  ◄─────────┴──────────────────────────────────────┘
                     │
                     └──► frontend overlays inference result on video at its own cadence
```

**FrameSlot semantics:**
- `put_frame(frame)` always succeeds; drops any existing frame (we want freshest, not all)
- `get_frame()` async-waits for a frame
- Backpressure is automatic: slow inference = older inferences shown longer; never blocks producer

**Configurable at runtime:**
- `inference_interval_ms` (default 1000, min 100)
- `target_resolution` (default `640x360`)
- `model_id` (cosmos-2b | cosmos-8b | vss — see AD-3)
- `prompt_preset` (see AD-6)

### AD-3: Model menu locked to exactly three options

| Selector value | Backend | What it is |
|---|---|---|
| `cosmos-2b` | vLLM serving `nvidia/Cosmos-Reason2-2B` | Default. Fast, ~200-500ms on RTX 5090 |
| `cosmos-8b` | vLLM serving `nvidia/Cosmos-Reason2-8B` | Heavy tier. ~1-2s, better reasoning |
| `vss` | NVIDIA VSS Blueprint endpoint | **Batch-only.** Not exposed in live selector. Used by recorded-video pipeline (AD-5). |

`build_detection_adapter` validates against this exact set and rejects anything else with a clear error. `OllamaAdapter`, `NvidiaNimAdapter`, and `MockDetectionAdapter` classes remain importable (mock is the test default; others are dev-only) but are **not in the runtime selector**.

**Default vLLM endpoint:** `http://localhost:8000/v1` (env: `VLLM_ENDPOINT`)
**Default model env:** `VLLM_MODEL=nvidia/Cosmos-Reason2-2B`

### AD-4: Why vLLM and not Ollama

- vLLM with PagedAttention + continuous batching is the throughput winner on x86 CUDA, especially for the batch VSS path
- For live (one stream → one inference at a time), the latency win is smaller but real (~30% on Cosmos-2B in NVIDIA's own benchmarks)
- One backend = one config surface. Two backends = matrix of versions, models, and quirks
- Ollama stays as a documented dev fallback (not in selector); user runs `OLLAMA_MODEL=... python -m vision.live_pipeline --legacy-ollama` if they need it on a non-CUDA box

### AD-5: Recorded-video → VSS as a separate batch pipeline

VSS is the **Video Search and Summarization Blueprint** — a multi-component NVIDIA reference deployment (VLM + LLM + retrieval DB), exposed as an HTTP endpoint. It is **not** a model you load. It is overkill for live inference and the right tool for recorded-video summarization.

**Live pipeline gets:** optional `--record-to <dir>` flag that writes rotating MP4 segments (e.g., 5-min) via ffmpeg subprocess. Subprocess ffmpeg is fine for *writing* — the lag problem was only about *reading*.

**New batch pipeline:**
- CLI: `vision summarize-recording --input <mp4> --vss-endpoint <url> --output <json>`
- API: `POST /recordings/{id}/summarize` returns `job_id`; `GET /recordings/{id}/summary` returns the summary when ready
- Async job runs in background task; status tracked in SQLite (reuse the existing `store/` from `operator-wrapper-brief.md` Commit 1)
- Output schema: `RecordingSummary { recording_id, duration_seconds, segments: [SegmentSummary], top_events: [TrafficEvent], generated_at, vss_endpoint }`

### AD-6: Traffic-domain prompt presets (not generic VLM prompts)

We do not ship "Describe what you see." We ship operator-relevant traffic prompts. Six presets, exposed in settings panel and selectable per inference call:

| Preset key | Prompt |
|---|---|
| `vehicle_count` | `"Count the vehicles visible in this image. Respond in this exact format: count=N | vehicle_types=car:N,truck:N,motorcycle:N | confidence=low|medium|high"` |
| `congestion` | `"Assess traffic congestion. Respond: status=clear|moderate|heavy | reasoning=one short sentence"` |
| `incident` | `"Describe any incident, collision, or anomaly visible. If none, respond: status=normal. Otherwise: status=incident | type=collision|stalled|debris|other | severity=info|warning|critical | description=one sentence"` |
| `wrong_way` | `"Is any vehicle moving against the marked traffic direction? Respond: status=yes|no | description=one short sentence"` |
| `lane_compliance` | `"Are vehicles in correct lanes? Respond: status=compliant|violation | description=one short sentence"` |
| `scene_description` | `"Describe the intersection scene in one sentence focused on operator-relevant detail (vehicles, pedestrians, signage state, weather, lighting)."` |

Parser layer (`vision/prompt_parsers.py`) parses each preset's response into structured fields populated onto `TrafficEvent.vlm_*` columns. Unparseable response → log warning, store raw text in `vlm_summary`, continue.

### AD-7: Structured output stays hybrid (do not change `TrafficEvent` schema beyond additive fields)

`TrafficEvent` gets three additive nullable fields (no breaking changes):

```python
vlm_summary: str | None = None      # human-readable one-liner from VLM
vlm_reasoning: str | None = None    # structured parse of preset response
vlm_model: str | None = None        # "cosmos-2b" | "cosmos-8b" | "vss"
```

Existing fields (`event_type`, `severity`, `vehicle_count`, `track_ids`, `confidence`) **stay populated from the deterministic mock or, in future, an ONNX YOLO adapter** — not from the VLM. VLM-only event population is fragile and out of scope for this brief.

## Out of scope (do not build)

- ONNX/YOLO real detection adapter — separate future brief
- Multi-camera WebRTC fan-out — one camera per peer connection for now
- TURN server / NAT traversal — LAN-only, STUN-only at MVP
- VSS-as-live-engine — VSS is batch-only per AD-5
- Replacement of the existing Vite/React UI with live-vlm-webui's UI — extend, don't replace
- Authentication for the WebRTC signaling endpoint — LAN-only at MVP (same posture as operator wrapper)
- Multi-model concurrent inference (e.g., 2B + 8B at the same time) — pick one model per session

## Commit plan

Four commits, in order. Each gets its own kickoff prompt in `docs/claude-code-kickoff.md`. **One commit per PR.** Do not bundle.

---

### COMMIT A — Foundation cleanup (small, surgical)

**Why this is first:** Don't start architectural work on a red main. CI has been failing for 7 consecutive runs since 2026-05-22.

**File changes:**
- `api/main.py:336` — fix `F821 Undefined name 'fastapi'`. Read the line, identify the bare `fastapi.<Something>` reference, add the missing import or fix the reference.
- All files reported by `ruff check api vision events analytics telemetry tests examples` — fix the 14 ruff errors. Most are `E501` (line length), `F401` (unused imports), `UP037` (quoted type annotations).
- `vision/live_pipeline.py` — in `build_detection_adapter`, lock the selector to exactly `{cosmos-2b, cosmos-8b, vss}`. All other selector values raise `ValueError` with a clear message listing the three allowed options. `OllamaAdapter`, `NvidiaNimAdapter`, `MockDetectionAdapter` import lines stay (other code may use them); they just don't appear in the selector branch. Defaults: `cosmos` resolves to `cosmos-2b` with `nvidia/Cosmos-Reason2-2B` and `VLLM_ENDPOINT` (not `NVIDIA_VISION_ENDPOINT`).
- `README.md` — delete the "Recommended GitHub About" block. Update the "Detection Adapter Strategy" section to reflect the locked three-model menu. Add a "Live vs Batch" decision sentence under Quick Start.
- `LICENSE` — add Apache 2.0 (matches NVIDIA reference projects; matches the upstream license of patterns we're adopting).

**Acceptance:**
- `ruff check api vision events analytics telemetry tests examples` exits 0
- `pytest -q` green
- CI green on main
- `python -c "from vision.live_pipeline import build_detection_adapter; build_detection_adapter('ollama')"` raises with the new message
- `python -c "from vision.live_pipeline import build_detection_adapter; build_detection_adapter('cosmos-2b', endpoint='http://localhost:8000/v1')"` returns a `VllmAdapter` or `NvidiaCosmosAdapter` (whichever the codebase consolidates on — pick one in this commit)

**Branch:** `claude-code-live-vlm-commit-a`

---

### COMMIT B — WebRTC + dual-loop architecture (THE BIG ONE)

**File creates:**
- `vision/webrtc/__init__.py`
- `vision/webrtc/signaling.py` — FastAPI router. `POST /webrtc/offer` accepts SDP offer, returns SDP answer. Uses aiortc `RTCPeerConnection`. One peer connection per session; track sessions in a module-level dict keyed by session_id (UUID).
- `vision/webrtc/track.py` — `IncomingVideoTrack(MediaStreamTrack)`. On each frame received, push to `FrameSlot.put_frame()`.
- `vision/frame_slot.py` — `FrameSlot` class. Backed by `asyncio.Queue(maxsize=1)`. `put_frame()` discards existing item if present, then puts. `get_frame()` awaits. Thread-safe is not required; asyncio-safe is.
- `vision/inference_loop.py` — `InferenceLoop` class. Owns the active `DetectionAdapter`, the active prompt preset, and `inference_interval_ms`. Started on FastAPI startup, stopped on shutdown. Loop: sleep(interval) → get latest frame → call adapter.infer() → publish result to `ResultBroadcaster`.
- `vision/result_broadcaster.py` — async pub/sub. Holds a list of subscriber `asyncio.Queue`s. SSE endpoint subscribes and yields events as they arrive.
- `api/routes/live_results.py` — `GET /live/results` SSE endpoint that streams `InferenceResult` events. Use `sse-starlette` (already in pyproject).
- `vision/prompt_parsers.py` — one parser function per preset key. Returns `ParsedVlmResponse { structured: dict, raw: str, parse_ok: bool }`.

**File modifies:**
- `api/main.py` — register the new routers (`webrtc/signaling.py`, `routes/live_results.py`). On startup, instantiate `FrameSlot`, `InferenceLoop`, `ResultBroadcaster` as module-level singletons and start the inference loop task. On shutdown, cancel cleanly.
- `vision/adapters.py` — add `prompt: str` argument to `DetectionAdapter.infer()`. Update all existing adapters. Mock returns deterministic synthetic VLM-style responses based on preset key.
- `vision/schemas.py` (or `events/schemas.py` — find the right one) — add `vlm_summary`, `vlm_reasoning`, `vlm_model` nullable fields to `TrafficEvent`.
- `vision/live_pipeline.py` — keep the CLI command, but route it through the new dual-loop architecture. Old ffmpeg-pipe path stays accessible behind `--legacy-ffmpeg` for one release, with a deprecation log warning on use. Plan to delete in next release.
- `pyproject.toml` — add `aiortc>=1.9`, `av>=12` to the base dependencies (live transport is core now).

**File creates (tests):**
- `tests/test_frame_slot.py` — `put_frame` overwrites, `get_frame` returns latest, concurrent put/get is safe
- `tests/test_inference_loop.py` — cadence honored (mock clock), busy inference doesn't compound, exception in adapter is logged and loop continues
- `tests/test_prompt_parsers.py` — each preset's parser handles canonical response, malformed response, empty response
- `tests/test_result_broadcaster.py` — multiple subscribers each see the event; subscriber cleanup works
- `tests/test_webrtc_signaling.py` — offer/answer SDP round-trip with a mock aiortc peer (the actual data plane is integration-tested out of CI)
- `tests/test_live_pipeline_dual_loop.py` — end-to-end with mock adapter: frame in → result out, display path independent of inference timing

**Acceptance:**
- Browser at `http://localhost:8080/web/` (or equivalent) shows live webcam video that does **not** stutter or freeze when inference is running
- VLM result text overlays the video, updating roughly every `inference_interval_ms`
- Pausing or unplugging the model server (vLLM down) does **not** freeze the video — only stops result updates
- `pytest -q` green
- CI green on main
- README updated with new architecture diagram (mermaid) and the WebRTC quick-start

**Out of scope for Commit B:**
- Settings UI (Commit C)
- Recording / VSS batch (Commit D)
- ONNX YOLO adapter
- RTSP-bridge implementation for IP cameras — can be stubbed; full implementation deferred to a follow-up commit

**Branch:** `claude-code-live-vlm-commit-b`

---

### COMMIT C — Settings panel in web/

**Prerequisite:** Commit B reviewed and merged to main.

**File creates (frontend, under `web/`):**
- `web/components/settings-panel.tsx` — slide-out panel with the four runtime settings
- `web/components/prompt-preset-picker.tsx` — radio group bound to the six AD-6 presets
- `web/lib/settings-store.ts` — zustand or equivalent local state; persists to `localStorage`; syncs to backend via `PUT /runtime/settings`

**File creates (backend):**
- `api/routes/runtime_settings.py` — `GET /runtime/settings` and `PUT /runtime/settings`. PUT validates: model in {cosmos-2b, cosmos-8b}, inference_interval_ms in [100, 60000], resolution in a fixed allowlist, prompt_preset in the six AD-6 keys. On valid PUT, updates the live `InferenceLoop` instance.

**File modifies:**
- `web/app/<layout-or-router>` — wire settings panel into the existing layout (don't add a new screen; this is a panel inside the live view)
- `vision/inference_loop.py` — add thread/asyncio-safe setters for `inference_interval_ms`, `model_id`, `prompt_preset`, `target_resolution`. Changes take effect on the next loop iteration; no restart required.

**File creates (tests):**
- `tests/test_runtime_settings.py` — GET defaults, PUT happy path, PUT rejects out-of-range interval, PUT rejects unknown model, PUT rejects unknown preset, settings change propagates to inference loop within one interval

**Acceptance:**
- Changing inference interval in the panel changes the live cadence within ~1 interval, no page reload
- Changing model triggers a switch (next inference uses the new model); the in-flight one finishes against the old model — do not cancel mid-call
- Settings persist across page reload via localStorage
- ruff + pytest green; CI green

**Branch:** `claude-code-live-vlm-commit-c`

---

### COMMIT D — Record + VSS batch pipeline

**Prerequisite:** Commit B reviewed and merged to main. Commit C optional but recommended.

**File creates:**
- `vision/recorder.py` — `RotatingRecorder` class. Wraps an ffmpeg subprocess that writes the current WebRTC track to MP4 segments of configurable length (default 5 min). Lifecycle: `start(output_dir, segment_seconds)`, `stop()`. On rotation, emits a `RecordingSegmentEvent` to the broadcaster so the operator UI can show "new recording available."
- `vision/summarizer.py` — `VssSummarizer` class. Async. Given an MP4 path and a VSS endpoint, chunks if needed (VSS endpoint may have a per-request length cap — handle 413 by chunking), POSTs to VSS, parses response, returns a `RecordingSummary`.
- `api/routes/recordings.py` —
  - `GET /recordings` — list available recordings (file system or DB)
  - `POST /recordings/{id}/summarize` — kicks off background task, returns `{job_id, status: "queued"}`
  - `GET /recordings/{id}/summary` — returns the summary if ready, or `{status: "in_progress" | "queued" | "failed", error?: str}`
- `events/schemas.py` — add `RecordingSummary`, `SegmentSummary`, `RecordingSegmentEvent` Pydantic models
- CLI: extend the existing CLI (likely in `vision/live_pipeline.py` or wherever Typer commands live) with `summarize-recording --input <mp4> --vss-endpoint <url> --output <json>`

**File modifies:**
- `vision/live_pipeline.py` — add `--record-to <dir>` flag. When set, instantiates `RotatingRecorder` alongside the inference loop.
- `store/schema.sql` (if it exists from operator-wrapper-brief Commit 1) — add `recording_summaries` table: `id, recording_path, status, summary_json, error, created_at, completed_at`. If `store/` doesn't exist yet, use a simple in-memory dict and TODO note.
- `pyproject.toml` — no new dependencies (ffmpeg is system binary; httpx already pulled in)

**File creates (tests):**
- `tests/test_recorder.py` — start/stop, rotation logic (mock ffmpeg subprocess via injection), output directory created
- `tests/test_summarizer.py` — chunking happens on simulated 413, request shape matches VSS spec (mocked endpoint via httpx mock), `RecordingSummary` populated correctly
- `tests/test_recordings_routes.py` — POST returns job_id, GET returns status transitions

**Acceptance:**
- Live session with `--record-to artifacts/recordings/` produces rotating MP4 segments
- `POST /recordings/{id}/summarize` returns a job_id within 100ms
- `GET /recordings/{id}/summary` eventually returns a populated `RecordingSummary` (against a mocked VSS endpoint in tests; against real VSS in manual verification)
- CLI command works against an MP4 and a (real or mocked) VSS endpoint
- ruff + pytest green; CI green

**Branch:** `claude-code-live-vlm-commit-d`

## Hardware assumptions (RTX 5090 dev box)

- **OS:** Ubuntu 22.04 or 24.04
- **GPU:** RTX 5090 with current CUDA / driver
- **Python:** 3.11+
- **vLLM:** install per [vllm docs](https://docs.vllm.io/), serving on `http://localhost:8000/v1`
- **Cosmos model download:** `huggingface-cli download nvidia/Cosmos-Reason2-2B` (and `-8B`)
- **VSS endpoint:** assumed available at `http://localhost:8001/v1` for testing; real VSS blueprint setup is operator-side, not part of this brief
- **Browser:** Chrome / Edge / Firefox — WebRTC works in all three; test in at least Chrome

For local dev without a GPU (e.g., when iterating UI), the mock adapter + `--legacy-ffmpeg` path stays functional.

## What "done" looks like for this whole brief

- All four commits merged to main, one PR each
- CI green on main throughout (each commit lands with green CI)
- Manual verification on RTX 5090: open the web UI, see live video at ~30 FPS, see VLM result overlay updating every ~1s, change inference interval in the settings panel and watch cadence change, switch model 2B→8B and see latency change, start a recording, stop it, summarize it via VSS, get a `RecordingSummary` back
- README documents: WebRTC quick-start, three-model menu, live vs batch decision, recording + summarization flow
- A short evidence artifact committed under `artifacts/` showing the end-to-end run (screenshot or short MP4 of the UI)

After this brief is done, the repo has a real, working live VLM engine that competes credibly with `live-vlm-webui` on the live path *and* offers something they don't: structured traffic events, operator review, RTSP camera profiles, traffic-domain use case packs, and recorded-video summarization via VSS.

## References

- [nvidia-ai-iot/live-vlm-webui](https://github.com/nvidia-ai-iot/live-vlm-webui) — pattern source for dual-loop + WebRTC + prompt editor
- [Jetson AI Lab tutorial: Live VLM WebUI](https://www.jetson-ai-lab.com/tutorials/live-vlm-webui/) — operator-facing description of the patterns we're adopting
- [aiortc docs](https://aiortc.readthedocs.io/) — WebRTC peer connection API
- [nvidia/Cosmos-Reason2-2B](https://huggingface.co/nvidia/Cosmos-Reason2-2B), [nvidia/Cosmos-Reason2-8B](https://huggingface.co/nvidia/Cosmos-Reason2-8B)
- [vLLM docs](https://docs.vllm.io/) — serving + OpenAI-compatible API
- [NVIDIA VSS Blueprint](https://build.nvidia.com/nvidia/video-search-and-summarization) — batch summarization endpoint
- `docs/operator-wrapper-brief.md` — the prior brief for operator review surface; coexists with this one
- `AGENTS.md` — repo-wide rules; still apply

## If anything in this brief is unclear or contradicts existing code, STOP and ask before implementing.
