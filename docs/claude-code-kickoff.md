# Claude Code Kickoff Prompts

Ready-to-paste prompts for the implementer (Claude Code on the other station).
Brief is at `docs/operator-wrapper-brief.md` — the implementer must read it
end-to-end before writing any code. Master rules at `AGENTS.md` still apply.

---

## Commit 1 — backend (packs + store + snapshot + endpoints)

```
Your sole authoritative spec is `docs/operator-wrapper-brief.md`. Read it
end-to-end before writing any code. `AGENTS.md` repo rules also apply:
Pydantic v2, mock adapter is the test default, no OpenCV/ONNX in core
event/analytics/telemetry modules, no autonomous enforcement.

Scope of this run: COMMIT 1 only — backend additions for the three use
case packs, the SQLite config store, the snapshot transport, and the new
API endpoints.

Implement the file list under "COMMIT 1 — backend" in the brief's section
4. That includes:
  - packs/ module (base, registry, compatibility, moving_object,
    speed_violation, stop_sign)
  - store/ module (schema.sql, config_store.py via aiosqlite)
  - transports/snapshot.py (single-image snapshot, cache-busted)
  - events/reporter.py (debouncer keyed by camera_id + track_id +
    pack_id, with report_interval_seconds hard floor of 2)
  - api/routes/ for cameras, use_cases, snapshot, metrics_extra, artifacts
  - All listed tests

Modifications limited to: events/schemas.py (add new event types and
subclasses), api/main.py (register routers + mount SQLite), pyproject.toml
(add aiosqlite and sse-starlette).

Hard guardrails:
- One commit. Do NOT implement Commit 2 (web) or Commit 3 (credibility
  polish) in this run.
- No new top-level packages beyond packs/, store/, transports/.
- Match existing code conventions: Pydantic v2, type hints, module-level
  singletons only in api/main.py.
- ruff check . and pytest -q must be green before commit.
- No commit trailers, no AI attribution, no co-author lines.
- Pack compatibility validator MUST be exhaustive over all 8 subsets of
  the 3 packs (frozenset({}), {1}, {2}, {3}, {1,2}, {1,3}, {2,3},
  {1,2,3}). Allowed sets are the six the brief calls out.
- report_interval_seconds is integer, >= 2, default 5. Save with 1 must
  return 422.
- PUT /cameras/{id}/bindings returns HTTP 422 with error codes
  "incompatible_pack_selection", "missing_prerequisite",
  "invalid_report_interval" as appropriate. Response body shape per
  brief.

Acceptance per the brief's COMMIT 1 section:
- Compatibility rule enforced at API
- report_interval lower bound enforced at API
- Pack 2 prerequisite (speed_calibration) enforced at API
- Pack 3 prerequisite (stop_zone) enforced at API
- Event reporter emits at most one event per (camera_id, track_id,
  pack_id) per interval, with terminal events exempt
- /metrics/kpis returns inference latency + flow counts with
  data_source badge wrapper
- ruff + pytest green

Push to a feature branch named `claude-code-commit-1`. Do not push to
main. When done, open with: "Ready for review."

If anything in the brief is unclear or contradicts existing code, STOP and
ask before implementing.
```

---

## Commit 2 — frontend (web/) — five screens, snapshot transport, SSE

> **Prerequisite:** Commit 1 reviewed and merged to main.

```
Your sole authoritative spec is `docs/operator-wrapper-brief.md`,
sections 2 and 4 COMMIT 2. Backend (Commit 1) is on main.

Scope of this run: COMMIT 2 only — Vite + React + TypeScript + Tailwind +
shadcn/ui frontend at apps/web/.

Implement per the brief's file layout in section 2.1 and the screen
acceptance criteria in section 2.2.

Scaffold:
- pnpm create vite web -- --template react-ts
- cd web && pnpm install
- pnpm add tailwindcss postcss autoprefixer
- pnpm dlx tailwindcss init -p
- pnpm dlx shadcn@latest init
- Add only these shadcn components: button, card, badge, input,
  scroll-area, skeleton, alert, dialog, tooltip

Five screens:
1. /live      — S1 Live Wall (snapshot grid + KPI strip)
2. /live/:id  — S2 Camera Detail (snapshot at 5 FPS, event sidebar)
3. /events    — S3 Event Feed (filterable, SSE-driven)
4. /studio    — S6 Use Case Studio (pack toggle grid, calibration
                 wizard, stop zone editor, report_interval editor)
5. /metrics   — S12 Metrics & KPIs (with data-source-badge on every tile)
6. /artifacts — S13 Evidence Artifacts (read-only browser)

Hard guardrails:
- One commit. Do NOT implement Commit 3 in this run.
- shadcn/ui only — no Material UI, no Chakra, no Ant Design
- useState + useEffect only — no Redux, no Zustand, no React Query
  (use fetch + simple cache; the wrapper is single-user)
- No streaming responses for chat
- No WebRTC, no MJPEG — snapshot only
- No auth, no login screen
- The §11.4 compatibility grid in /studio must disable toggles in real
  time and surface the tooltip text from the brief; clicking a disabled
  cell does nothing; the API still returns 422 if a forbidden set is
  submitted (defense in depth)
- The credibility banner appears on /live, /metrics, /artifacts when the
  active adapter is mock
- pnpm build must succeed
- Root .gitignore must exclude web/node_modules, web/dist, web/.env.local
- Multi-stage Dockerfile: amd64 Node build stage → copy web/dist into
  existing aarch64 final image; no Node runtime in final image

Acceptance per the brief's COMMIT 2 section:
- cd web && pnpm install && pnpm dev starts on :3000
- With backend on :8080, opening / redirects to /live and renders grid
- Selecting {2,3} or {1,2,3} in /studio shows tooltip and disables save
- Saving valid bindings persists; audit row recorded
- pnpm build green, no console errors

Push to branch `claude-code-commit-2`. Do not push to main.
```

---

## Commit 3 — credibility wiring + KPI dashboard polish

> **Prerequisite:** Commit 2 reviewed and merged to main.

```
Your sole authoritative spec is `docs/operator-wrapper-brief.md`,
sections 2.3 and 4 COMMIT 3. Commits 1 and 2 are on main.

Scope of this run: COMMIT 3 only — finalize the credibility-boundary
mechanics and the Metrics & KPIs dashboard.

Implement per the brief:
- Every /metrics/* response carries data_source + tooltip
- web/components/data-source-badge.tsx with three visual variants
  (muted dotted-border for mock, default for live-rtsp, solid for
  validated-benchmark)
- web/components/credibility-banner.tsx — persistent + dismissible per
  session (dismissal stored in localStorage)
- /metrics page full layout: status strip, KPI tiles, time-series,
  per-class bars, congestion timeline, mock evidence card, benchmark
  cards (CPU baseline, RTX 5090 dev, Jetson Thor — empty state if
  artifact missing)
- /artifacts page read-only browser — pretty JSON viewer with copy +
  download
- jetson_benchmark tile reads from
  artifacts/reports/jetson-benchmark.json if present; empty state with
  "Roadmap item #3" link if not

Hard guardrails:
- One commit
- The badge MUST be sourced server-side from
  DetectionAdapter.metadata; client may not decide it
- Unvalidated metrics (CPU/GPU benchmark, Jetson benchmark) NEVER
  display fabricated numbers — empty state only
- Mock-data tooltip text must match PORTFOLIO_DELIVERABLES.md verbatim:
  "Mock adapter — does not prove real camera accuracy, Jetson latency,
   TensorRT acceleration, or automated enforcement readiness."
- pnpm build green
- pytest + ruff green

Push to branch `claude-code-commit-3`. Do not push to main.
```

---

## After each commit

The reviewer (Claude in this conversation) will:
1. Verify scope matches the brief — no scope creep
2. Run git diff and inspect key files
3. Check ruff + pytest in CI (and pnpm build for web commits)
4. Verify the compatibility rule + report_interval enforcement
5. Verify the credibility badge is honest
6. Approve merge or request specific changes

Cosmetic differences that meet acceptance criteria are accepted as
written. Functional deviations from the brief require a brief amendment
before re-implementation.

---

# Live VLM Engine — Commits A through D

> **Authoritative spec for all four commits below:** `docs/live-vlm-engine-brief.md`.
> Read it end-to-end before writing any code. `AGENTS.md` repo rules still apply.

These commits rebuild the live video + VLM inference engine and add a
recorded-video → VSS batch pipeline. Hardware target: **RTX 5090 dev box, Ubuntu 22.04/24.04**.

## Commit A — DONE on main (no agent action needed)

> **Status:** Completed in the reviewer session on 2026-05-26.
> **What landed:** F821 + 13 ruff errors fixed; `build_detection_adapter`
> locked to `{cosmos-2b, cosmos-8b, vss}` with `nvidia-cosmos` /
> `nvidia-vss` / `cosmos` aliases; tests updated to match the locked
> menu; LICENSE (Apache 2.0) added; README "Recommended GitHub About"
> block removed; README Detection Adapter Strategy rewritten; live-vs-batch
> note added under Quick Start.
> **Verify:** `python -m ruff check api vision events analytics telemetry tests examples` exits 0.
>
> **Start at Commit B below.**

<details>
<summary>Original Commit A prompt (kept for history)</summary>

```
Your sole authoritative spec is `docs/live-vlm-engine-brief.md`, section
"COMMIT A — Foundation cleanup". `AGENTS.md` repo rules also apply.

Scope of this run: COMMIT A only — small surgical cleanup so subsequent
commits start from green CI and a locked model menu.

Do exactly this:
1. Fix the `F821 Undefined name 'fastapi'` at api/main.py:336. Read the
   line, identify the bare fastapi.<X> reference, add the missing import
   or correct the reference.
2. Fix all ruff errors reported by:
     ruff check api vision events analytics telemetry tests examples
   Most are E501 (line length), F401 (unused imports), UP037 (quoted type
   annotations). No behavior changes; this is style only.
3. In vision/live_pipeline.py:build_detection_adapter, lock the selector
   to exactly {cosmos-2b, cosmos-8b, vss}. Any other selector value raises
   ValueError with a message listing the three allowed options. Default
   for "cosmos" or "cosmos-2b" resolves to nvidia/Cosmos-Reason2-2B served
   via VLLM_ENDPOINT (default http://localhost:8000/v1).
   OllamaAdapter, NvidiaNimAdapter, MockDetectionAdapter imports stay
   (other code uses them); they are not in the selector branch.
4. Add LICENSE — Apache 2.0, standard text, Copyright 2026 Obinna Edeh.
5. README.md edits:
   - Delete the "Recommended GitHub About" block entirely
   - Update "Detection Adapter Strategy" section to reflect the locked
     three-model menu (cosmos-2b, cosmos-8b, vss)
   - Under "Quick Start", add a one-sentence Live vs Batch decision:
     "Use the live endpoint for real-time monitoring; use the
     summarize-recording CLI for after-the-fact VSS analysis."
   - Do NOT add new sections; this is cleanup, not expansion

Hard guardrails:
- One commit. Do NOT start Commit B work in this run.
- No new dependencies in pyproject.toml in this commit.
- No new top-level packages.
- ruff check . and pytest -q MUST be green before commit.
- No commit trailers, no AI attribution, no co-author lines.

Acceptance per the brief's COMMIT A section:
- ruff check api vision events analytics telemetry tests examples exits 0
- pytest -q green
- CI green on main
- python -c "from vision.live_pipeline import build_detection_adapter; build_detection_adapter('ollama')" raises with the new "only cosmos-2b, cosmos-8b, vss allowed" message
- python -c "from vision.live_pipeline import build_detection_adapter; build_detection_adapter('cosmos-2b', endpoint='http://localhost:8000/v1')" returns an adapter instance
- LICENSE file exists with Apache 2.0 text
- README "Recommended GitHub About" block is gone

Push to branch `claude-code-live-vlm-commit-a`. Do not push to main.

If anything in the brief is unclear or contradicts existing code, STOP
and ask before implementing.
```

</details>

---

## Commit B — WebRTC + dual-loop architecture (the big one)

> **Prerequisite:** Commit A is on main (already landed).

```
Your sole authoritative spec is `docs/live-vlm-engine-brief.md`, sections
"AD-1", "AD-2", "AD-6", "AD-7", and "COMMIT B — WebRTC + dual-loop
architecture". `AGENTS.md` repo rules also apply. Commit A is on main.

Scope of this run: COMMIT B only — replace the FFmpeg-pipe live transport
with browser-WebRTC via aiortc, split display loop from inference loop,
add SSE result stream, populate vlm_* fields on TrafficEvent.

Implement the file list under "COMMIT B" in the brief. Create:
  - vision/webrtc/__init__.py
  - vision/webrtc/signaling.py        (POST /webrtc/offer, SDP exchange)
  - vision/webrtc/track.py            (IncomingVideoTrack pushing to FrameSlot)
  - vision/frame_slot.py              (asyncio.Queue(maxsize=1), overwrite-on-put)
  - vision/inference_loop.py          (sampler at inference_interval_ms)
  - vision/result_broadcaster.py      (async pub/sub for inference results)
  - api/routes/live_results.py        (GET /live/results SSE endpoint)
  - vision/prompt_parsers.py          (one parser per AD-6 preset)

Modify:
  - api/main.py — register new routers, start/stop inference loop on
    FastAPI startup/shutdown
  - vision/adapters.py — add prompt: str argument to
    DetectionAdapter.infer(); update all adapters; mock returns
    deterministic synthetic VLM responses keyed by preset
  - vision/schemas.py or events/schemas.py (find the right one) — add
    nullable vlm_summary: str, vlm_reasoning: str, vlm_model: str fields
    to TrafficEvent
  - vision/live_pipeline.py — route CLI through new architecture; keep
    --legacy-ffmpeg flag for the old path with a deprecation warning
  - pyproject.toml — add aiortc>=1.9, av>=12 to base dependencies

Tests required:
  - tests/test_frame_slot.py
  - tests/test_inference_loop.py
  - tests/test_prompt_parsers.py
  - tests/test_result_broadcaster.py
  - tests/test_webrtc_signaling.py        (mock peer; data plane is integration-tested out of CI)
  - tests/test_live_pipeline_dual_loop.py (mock adapter end-to-end)

Hard guardrails:
- One commit. Do NOT start Commit C or D in this run.
- Settings panel is NOT in this commit — that's Commit C.
- Recording / VSS is NOT in this commit — that's Commit D.
- RTSP bridge for IP cameras may be stubbed; full implementation is a
  follow-up commit.
- Mock adapter remains the test default. NO test may require a real model
  or a vLLM server.
- aiortc adds aiortc and av to base deps — this is intentional; live
  transport is core now.
- Match existing code conventions: Pydantic v2, type hints, module-level
  singletons only in api/main.py.
- ruff check . and pytest -q MUST be green before commit.
- No commit trailers, no AI attribution, no co-author lines.

Acceptance per the brief's COMMIT B section:
- Browser at the served URL shows live webcam video that does NOT
  stutter or freeze when inference is running
- VLM result text overlays the video and updates roughly every
  inference_interval_ms
- Killing the vLLM server does NOT freeze the video; only stops result
  updates
- pytest -q green; ruff green; CI green
- README updated with mermaid architecture diagram and WebRTC quick-start

Push to branch `claude-code-live-vlm-commit-b`. Do not push to main.

If anything in the brief is unclear or contradicts existing code, STOP
and ask before implementing.
```

---

## Commit C — Settings panel in web/

> **Prerequisite:** Commit B reviewed and merged to main.

```
Your sole authoritative spec is `docs/live-vlm-engine-brief.md`, sections
"AD-6" and "COMMIT C — Settings panel in web/". `AGENTS.md` repo rules
also apply. Commits A and B are on main.

Scope of this run: COMMIT C only — settings panel in the existing
Vite/React app at web/ that lets the operator change inference cadence,
target resolution, model, and prompt preset at runtime, plus the backend
endpoint to apply those changes.

Create (frontend, under web/):
  - web/components/settings-panel.tsx        (slide-out panel)
  - web/components/prompt-preset-picker.tsx  (radio group over six AD-6 presets)
  - web/lib/settings-store.ts                (local state + localStorage persistence)

Create (backend):
  - api/routes/runtime_settings.py
      GET /runtime/settings    — returns current settings
      PUT /runtime/settings    — validates + applies; updates live InferenceLoop

Modify:
  - web/app/<layout-or-router> — wire settings panel into the existing
    live view; do NOT add a new top-level screen
  - vision/inference_loop.py — add async-safe setters for
    inference_interval_ms, model_id, prompt_preset, target_resolution.
    Changes take effect on the next loop iteration; do NOT cancel an
    in-flight inference call.

Tests required:
  - tests/test_runtime_settings.py
      - GET returns defaults
      - PUT happy path
      - PUT 422 on interval out of [100, 60000]
      - PUT 422 on unknown model (not in {cosmos-2b, cosmos-8b})
      - PUT 422 on unknown preset
      - settings change propagates to the inference loop within one interval

Hard guardrails:
- One commit. Do NOT touch recording / VSS in this run (Commit D).
- No new screens — this is a panel inside the live view
- No new state libraries beyond what web/ already uses; if a tiny store
  is needed, write 30 lines, do not pull in zustand if existing patterns
  are simpler
- VSS is NOT a valid live model in the settings UI — only cosmos-2b and
  cosmos-8b appear in the model selector. VSS is batch-only (Commit D).
- Inference interval lower bound 100ms, upper bound 60000ms — hard
- An in-flight inference call MUST complete against the model that
  started it, even if the user switched models mid-call

Acceptance per the brief's COMMIT C section:
- Changing inference interval changes the live cadence within ~1
  interval, no page reload
- Changing model triggers a switch on the next inference call
- Settings persist across page reload (localStorage)
- ruff + pytest green; CI green; pnpm build green

Push to branch `claude-code-live-vlm-commit-c`. Do not push to main.

If anything in the brief is unclear or contradicts existing code, STOP
and ask before implementing.
```

---

## Commit D — Record + VSS batch pipeline

> **Prerequisite:** Commit B reviewed and merged to main. Commit C optional.

```
Your sole authoritative spec is `docs/live-vlm-engine-brief.md`, sections
"AD-5" and "COMMIT D — Record + VSS batch pipeline". `AGENTS.md` repo
rules also apply. Commit B is on main; Commit C may be on main.

Scope of this run: COMMIT D only — rotating MP4 recorder alongside the
live pipeline, VSS summarizer for recorded MP4s, CLI + API + tests.

Create:
  - vision/recorder.py         (RotatingRecorder: ffmpeg subprocess writing rotating MP4)
  - vision/summarizer.py       (VssSummarizer: async, chunks on 413, hits VSS endpoint)
  - api/routes/recordings.py
      GET  /recordings                       — list
      POST /recordings/{id}/summarize        — kick off background task, return {job_id, status}
      GET  /recordings/{id}/summary          — return summary if ready, else status

Modify:
  - events/schemas.py — add RecordingSummary, SegmentSummary,
    RecordingSegmentEvent Pydantic models
  - vision/live_pipeline.py — add --record-to <dir> flag; when set,
    instantiate RotatingRecorder alongside the inference loop. Also add
    new CLI command: `summarize-recording --input <mp4> --vss-endpoint
    <url> --output <json>`
  - store/schema.sql (if it exists from operator-wrapper-brief Commit 1)
    — add recording_summaries table. If store/ does not exist yet, use a
    module-level dict and leave a TODO note pointing to operator-wrapper
    Commit 1

Tests required:
  - tests/test_recorder.py
      - start/stop lifecycle
      - rotation logic (mock ffmpeg subprocess via injection)
      - output directory created if missing
  - tests/test_summarizer.py
      - chunking on simulated 413
      - request shape matches VSS spec (mock endpoint via httpx)
      - RecordingSummary populated correctly
  - tests/test_recordings_routes.py
      - POST returns job_id within 100ms
      - GET returns status transitions

Hard guardrails:
- One commit.
- ffmpeg subprocess for WRITING is fine — the live-path lag rule about
  not using ffmpeg subprocesses applies only to READING live frames
- No new dependencies; httpx and ffmpeg are already available
- VSS endpoint is HTTP — do not assume any specific VSS Blueprint
  version; the adapter should be tolerant of minor response-shape
  differences via Pydantic with extra='ignore'
- Background tasks use FastAPI's BackgroundTasks or a simple asyncio
  task — do NOT pull in Celery / RQ / Dramatiq
- If a long summarization fails, the job status MUST move to "failed"
  with an error message; never silently hang

Acceptance per the brief's COMMIT D section:
- Live session with --record-to artifacts/recordings/ produces rotating
  MP4 segments
- POST /recordings/{id}/summarize returns a job_id within 100ms
- GET /recordings/{id}/summary eventually returns a populated
  RecordingSummary (against mocked VSS in tests; against real VSS in
  manual verification)
- CLI summarize-recording works against an MP4 and a (mocked or real)
  VSS endpoint
- ruff + pytest green; CI green

Push to branch `claude-code-live-vlm-commit-d`. Do not push to main.

If anything in the brief is unclear or contradicts existing code, STOP
and ask before implementing.
```

---

## After Commit D

The reviewer (Claude in this conversation) will verify the
end-to-end "done" definition in `docs/live-vlm-engine-brief.md` —
specifically the manual RTX 5090 verification list — and request a short
evidence artifact under `artifacts/` (screenshot or short MP4) showing
the working end-to-end flow.
