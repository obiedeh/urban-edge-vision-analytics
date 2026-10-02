import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type Camera, type CameraState, type TrafficEvent } from "@/lib/api";
import { useLiveResults } from "@/lib/live-results";
import { RuntimeStatusBar, useRuntimeStatus } from "@/components/runtime-status-bar";
import { LiveVideo } from "@/components/live-video";
import { CameraStateChip, ProfileChip, SeverityChip } from "@/components/status-chip";
import { EventPackFields, eventLabel } from "@/components/event-fields";
import { CredibilityBanner } from "@/components/credibility-banner";
import { cn, formatMs, formatSeconds, formatTs } from "@/lib/utils";
import { Radio, WifiOff, Camera as CameraIcon } from "lucide-react";

const EVENTS_POLL_MS = 3_000;
const MAX_EVENTS = 50;
// Browsers allow ~6 concurrent HTTP/1.1 connections per host. The main MJPEG stream and the
// SSE results feed hold two; keep the live thumbnails to two more so polling fetches never starve.
const MAX_MJPEG_THUMBS = 2;

// ── Recent events side panel ──────────────────────────────────────────────────

function EventsPanel({ cameraId }: { cameraId: string }) {
  const [events, setEvents] = useState<TrafficEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const seen = useRef<Set<string>>(new Set());

  useEffect(() => {
    let dead = false;
    setEvents([]); setLoading(true); seen.current = new Set();
    const load = async (limit: number) => {
      try {
        const fresh = await api.events.list({ camera_id: cameraId, limit });
        if (dead) return;
        const incoming = fresh.filter((e) => !seen.current.has(e.event_id));
        incoming.forEach((e) => seen.current.add(e.event_id));
        if (incoming.length) setEvents((prev) => [...incoming, ...prev].sort((a, b) => b.timestamp.localeCompare(a.timestamp)).slice(0, MAX_EVENTS));
      } catch { /* keep the last list */ }
      finally { if (!dead) setLoading(false); }
    };
    load(30);
    const t = setInterval(() => load(20), EVENTS_POLL_MS);
    return () => { dead = true; clearInterval(t); };
  }, [cameraId]);

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden flex flex-col">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <div className="flex items-center gap-2">
          <Radio className="h-3.5 w-3.5 text-emerald-400 animate-pulse" />
          <span className="text-xs font-semibold text-foreground">Recent events</span>
        </div>
        <Link to={`/events?camera_id=${encodeURIComponent(cameraId)}`} className="text-[10px] text-primary/80 hover:text-primary">All events</Link>
      </div>
      {loading ? (
        <div className="px-4 py-6 text-center text-xs text-muted-foreground animate-pulse">Loading…</div>
      ) : events.length === 0 ? (
        <div className="px-4 py-8 text-center text-xs text-muted-foreground">No events yet for this camera. Pack events appear here as they are emitted.</div>
      ) : (
        <div className="divide-y divide-border overflow-y-auto max-h-[32rem]">
          {events.map((evt) => (
            <Link
              key={evt.event_id}
              to={`/events?event_id=${encodeURIComponent(evt.event_id)}`}
              className={cn("block px-3 py-2 hover:bg-secondary/30 transition-colors", evt.severity === "critical" && "border-l-2 border-l-red-500/60", evt.severity === "warning" && "border-l-2 border-l-yellow-500/60")}
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className="font-mono text-[10px] text-muted-foreground/60 tabular-nums shrink-0">{formatTs(evt.timestamp)}</span>
                <span className="flex-1 text-xs font-medium truncate text-foreground">{eventLabel(evt)}</span>
                <SeverityChip severity={evt.severity} />
              </div>
              <EventPackFields evt={evt} className="mt-1 pl-[3.6rem]" />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Root page ─────────────────────────────────────────────────────────────────

export function LivePage() {
  const { id: routeId } = useParams<{ id?: string }>();
  const navigate = useNavigate();
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [liveIds, setLiveIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [focusId, setFocusId] = useState<string | null>(routeId ?? null);
  const { status: runtime } = useRuntimeStatus(2000);
  const { results, connected } = useLiveResults(undefined, true);

  // Load camera list + live settings; refresh the list every 10 s so added cameras appear.
  useEffect(() => {
    let dead = false;
    const load = async () => {
      try {
        const [cams, live] = await Promise.all([api.cameras.list(), api.settings.live().catch(() => ({ camera_ids: [] }))]);
        if (dead) return;
        setCameras(cams);
        setLiveIds(live.camera_ids ?? []);
      } catch { /* leave as is */ }
      finally { if (!dead) setLoading(false); }
    };
    load();
    const t = setInterval(load, 10_000);
    return () => { dead = true; clearInterval(t); };
  }, []);

  const liveCameras = useMemo(() => {
    const base = cameras.filter((c) => c.enabled && c.show_on_live);
    if (liveIds.length === 0) return base;
    const allowed = new Set(liveIds);
    const picked = base.filter((c) => allowed.has(c.id));
    return picked.length > 0 ? picked : base;
  }, [cameras, liveIds]);

  // Keep focus valid and in sync with the /live/:id route.
  useEffect(() => {
    if (routeId && routeId !== focusId) setFocusId(routeId);
  }, [routeId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (liveCameras.length === 0) return;
    if (!focusId || !liveCameras.some((c) => c.id === focusId)) {
      const first = liveCameras[0].id;
      setFocusId(first);
    }
  }, [liveCameras, focusId]);

  function focus(id: string) {
    setFocusId(id);
    navigate(routeId ? `/live/${encodeURIComponent(id)}` : "/live", { replace: true });
  }

  const focused = liveCameras.find((c) => c.id === focusId) ?? null;
  const others = liveCameras.filter((c) => c.id !== focusId);
  const runtimeById = useMemo(() => new Map((runtime?.cameras ?? []).map((c) => [c.camera_id, c])), [runtime]);
  const isMock = runtime?.model?.backend === "mock";
  const focusedRuntime = focused ? runtimeById.get(focused.id) ?? null : null;
  const focusedResult = focused ? results[focused.id] ?? null : null;

  return (
    <div className="space-y-0">
      <RuntimeStatusBar status={runtime} />

      <div className="p-4 space-y-4">
        {isMock && <CredibilityBanner />}

        <div className="flex items-center justify-between flex-wrap gap-2">
          <h1 className="text-lg font-semibold">Live</h1>
          <div className="flex items-center gap-2 flex-wrap">
            {liveCameras.map((cam) => {
              const rt = runtimeById.get(cam.id);
              return (
                <button
                  key={cam.id}
                  onClick={() => focus(cam.id)}
                  className={cn(
                    "flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors",
                    cam.id === focusId ? "border-primary/60 bg-primary/15 text-foreground" : "border-border text-muted-foreground hover:text-foreground hover:border-primary/40"
                  )}
                >
                  <span className={cn("h-1.5 w-1.5 rounded-full", rt?.state === "streaming" ? "bg-emerald-400" : rt?.state === "error" ? "bg-red-400" : "bg-muted-foreground/40")} />
                  {cam.name || cam.id}
                  <ProfileChip profile={cam.profile} />
                </button>
              );
            })}
            <span className="text-[10px] text-muted-foreground">
              {connected ? "results: live" : "results: reconnecting…"}
            </span>
          </div>
        </div>

        {loading && <div className="aspect-video w-full max-w-4xl rounded-lg snapshot-shimmer" />}

        {!loading && liveCameras.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20 text-muted-foreground gap-2">
            <WifiOff className="h-8 w-8" />
            <p className="text-sm">{cameras.length === 0 ? "No cameras configured." : "No enabled camera is marked \"Show on Live\"."}</p>
            <p className="text-xs">
              Go to <Link to="/cameras" className="text-primary underline underline-offset-2">Cameras</Link> to {cameras.length === 0 ? "add one" : "enable one"}.
            </p>
          </div>
        )}

        {!loading && focused && (
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <div className="xl:col-span-2 space-y-3">
              <div className="rounded-lg border border-border overflow-hidden bg-card">
                <div className="flex items-center justify-between px-3 py-2 border-b border-border gap-2 flex-wrap">
                  <div className="flex items-center gap-2 min-w-0">
                    <CameraIcon className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="text-xs font-medium text-foreground truncate">{focused.name || focused.id}</span>
                    <ProfileChip profile={focused.profile} />
                    {focused.masked_url && <span className="font-mono text-[10px] text-muted-foreground/60 truncate max-w-[280px]" title={focused.masked_url}>{focused.masked_url}</span>}
                  </div>
                  <Link to={`/studio?camera_id=${encodeURIComponent(focused.id)}`} className="text-[10px] text-primary/80 hover:text-primary">Studio</Link>
                </div>
                <LiveVideo camera={focused} result={focusedResult} runtime={focusedRuntime} />
                {/* status strip */}
                <div className="flex items-center gap-4 flex-wrap px-3 py-2 border-t border-border text-[11px] text-muted-foreground tabular-nums">
                  <CameraStateChip state={focusedRuntime?.state ?? focused.runtime?.state} />
                  <span>fps <b className="text-foreground font-medium">{focusedRuntime ? focusedRuntime.fps.toFixed(1) : "—"}</b></span>
                  <span>dropped <b className="text-foreground font-medium">{focusedRuntime?.frames_dropped ?? "—"}</b></span>
                  <span>reconnects <b className="text-foreground font-medium">{focusedRuntime?.reconnects ?? "—"}</b></span>
                  <span>uptime <b className="text-foreground font-medium">{formatSeconds(focusedRuntime?.uptime_s)}</b></span>
                  {focusedRuntime?.packs && focusedRuntime.packs.active_packs.length > 0 && (
                    <span>packs <b className="text-foreground font-medium">{focusedRuntime.packs.active_packs.join(", ")}</b> · tracks {focusedRuntime.packs.tracks} · events {focusedRuntime.packs.events_emitted}</span>
                  )}
                  <span className="ml-auto">
                    inference{" "}
                    <b className={cn("font-medium", focusedRuntime?.last_inference?.status === "ok" ? "text-emerald-400" : "text-yellow-400")}>
                      {focusedRuntime?.last_inference?.status ?? "—"}
                    </b>
                    {focusedRuntime?.last_inference && <> · {formatSeconds(focusedRuntime.last_inference.age_s)} ago · {formatMs(focusedRuntime.last_inference.latency_ms)}</>}
                  </span>
                </div>
                {focusedRuntime?.state === "error" && focusedRuntime.last_error && (
                  <div className="px-3 py-2 border-t border-red-500/30 bg-red-500/10 text-[11px] text-red-300 break-words">{focusedRuntime.last_error}</div>
                )}
                {focusedRuntime?.packs?.last_error && (
                  <div className="px-3 py-2 border-t border-yellow-500/30 bg-yellow-500/10 text-[11px] text-yellow-300 break-words">Pack error: {focusedRuntime.packs.last_error}</div>
                )}
              </div>

              {others.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Other cameras</p>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                    {others.map((cam, i) => (
                      <Thumb
                        key={cam.id}
                        camera={cam}
                        state={runtimeById.get(cam.id)?.state ?? cam.runtime?.state ?? null}
                        detections={results[cam.id]?.vehicle_count ?? null}
                        mode={i < MAX_MJPEG_THUMBS ? "mjpeg" : "snapshot"}
                        onClick={() => focus(cam.id)}
                      />
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="space-y-3">
              <EventsPanel cameraId={focused.id} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Thumb({
  camera, state, detections, mode, onClick,
}: {
  camera: Camera;
  state: CameraState | null;
  detections: number | null;
  mode: "mjpeg" | "snapshot";
  onClick: () => void;
}) {
  const isWebcam = camera.profile === "browser_webrtc";
  const [snap, setSnap] = useState(() => api.stream.snapshotUrl(camera.id));
  const [err, setErr] = useState(false);
  useEffect(() => {
    if (mode !== "snapshot") return;
    const t = setInterval(() => setSnap(api.stream.snapshotUrl(camera.id)), 2000);
    return () => clearInterval(t);
  }, [mode, camera.id]);
  useEffect(() => { setErr(false); }, [camera.id, state]);

  return (
    <button onClick={onClick} className="group relative block rounded-lg border border-border overflow-hidden bg-black aspect-video hover:border-primary/50 transition-colors text-left">
      {!isWebcam && !err && (
        <img
          src={mode === "mjpeg" ? api.stream.mjpegUrl(camera.id, 5) : snap}
          alt={camera.name}
          className="absolute inset-0 w-full h-full object-cover"
          onError={() => setErr(true)}
        />
      )}
      {(isWebcam || err) && (
        <div className="absolute inset-0 flex items-center justify-center text-muted-foreground/60 text-[10px]">
          {isWebcam ? "browser webcam — open to share" : "no signal"}
        </div>
      )}
      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-background/95 to-transparent px-2 py-1.5 flex items-end justify-between gap-1">
        <span className="text-[11px] font-medium text-foreground truncate">{camera.name || camera.id}</span>
        <div className="flex items-center gap-1 shrink-0">
          {detections != null && <span className="text-[9px] text-muted-foreground font-mono">{detections} det</span>}
          <CameraStateChip state={state} />
        </div>
      </div>
    </button>
  );
}
