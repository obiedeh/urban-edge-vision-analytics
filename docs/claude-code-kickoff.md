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
