import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Camera, type KpisResponse, type TrafficEvent } from "@/lib/api";
import { CredibilityBanner } from "@/components/credibility-banner";
import { PipelineStatusBar } from "@/components/pipeline-status-bar";
import { cn } from "@/lib/utils";
import { Wifi, WifiOff, AlertTriangle, Maximize2, ChevronDown, Radio, Clock } from "lucide-react";

const GRID_FPS = 1;
const STALE_WARN_MS = 10_000;
const STALE_OFFLINE_MS = 30_000;
const EVENTS_POLL_MS = 3_000;
const MAX_EVENTS_DISPLAY = 50;

function cameraStatus(lastAt: number | null): "online" | "degraded" | "offline" {
  if (lastAt === null) return "offline";
  const age = Date.now() - lastAt;
  if (age > STALE_OFFLINE_MS) return "offline";
  if (age > STALE_WARN_MS) return "degraded";
  return "online";
}

function StatusBadge({ status }: { status: "online" | "degraded" | "offline" }) {
  const cls = {
    online: "bg-emerald-500/20 text-emerald-400 border-emerald-500/40",
    degraded: "bg-yellow-500/20 text-yellow-400 border-yellow-500/40",
    offline: "bg-red-500/20 text-red-400 border-red-500/40",
  }[status];
  const Icon = status === "online" ? Wifi : status === "degraded" ? AlertTriangle : WifiOff;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold border",
        cls
      )}
    >
      <Icon className="h-3 w-3" />
      {status.toUpperCase()}
    </span>
  );
}

function CameraSourceBadge({ camera }: { camera: Camera }) {
  if (camera.synthetic) {
    return (
      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-semibold border bg-yellow-500/20 text-yellow-400 border-yellow-500/40">
        🎭 SYNTHETIC
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-semibold border bg-emerald-500/20 text-emerald-400 border-emerald-500/40">
      📷 LIVE
    </span>
  );
}

function SnapshotTile({ camera, compact = false }: { camera: Camera; compact?: boolean }) {
  const [src, setSrc] = useState<string>("");
  const [lastAt, setLastAt] = useState<number | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    function refresh() {
      // Set src to trigger a new image load; update lastAt only on successful load
      setSrc(api.snapshotUrl(camera.id));
    }
    refresh();
    intervalRef.current = setInterval(refresh, 1000 / GRID_FPS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [camera.id]);

  const status = cameraStatus(lastAt);

  return (
    <div className="group relative block rounded-lg border border-border overflow-hidden bg-card">
      {src ? (
        <img
          src={src}
          alt={`Camera ${camera.name}`}
          className={cn("w-full object-cover", compact ? "h-28" : "h-40")}
          onLoad={() => setLastAt(Date.now())}
          onError={() => setLastAt(null)}
        />
      ) : (
        <div className={cn("w-full snapshot-shimmer", compact ? "h-28" : "h-40")} />
      )}
      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-background/90 to-transparent px-2 py-2 flex items-end justify-between gap-1">
        <span className="text-xs font-medium text-foreground truncate leading-tight">{camera.name || camera.id}</span>
        <div className="flex items-center gap-1 shrink-0">
          <CameraSourceBadge camera={camera} />
          <StatusBadge status={status} />
        </div>
      </div>
    </div>
  );
}

// ── Event feed constants ──────────────────────────────────────────────────────

const EVENT_LABELS: Record<string, string> = {
  vehicle_detected:     "Moving Object Detected",
  scene_clear:          "No moving object detected",
  congestion_onset:     "Congestion onset",
  congestion_clear:     "Congestion cleared",
  stop_violation:       "Stop violation",
  speed_violation:      "Speed violation",
  pedestrian_detected:  "Pedestrian",
  object_left:          "Object left",
};

const SEVERITY_ROW_CLS: Record<string, string> = {
  info:     "",
  warning:  "bg-yellow-500/5 border-l-2 border-l-yellow-500/60",
  critical: "bg-red-500/5 border-l-2 border-l-red-500/60",
};

const SEVERITY_BADGE_CLS: Record<string, string> = {
  info:     "bg-blue-500/10 text-blue-400 border-blue-500/20",
  warning:  "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
  critical: "bg-red-500/10 text-red-400 border-red-500/20",
};

const EVENT_TYPE_TEXT_CLS: Record<string, string> = {
  vehicle_detected:  "text-muted-foreground",
  scene_clear:       "text-muted-foreground/50 italic",
  congestion_onset:  "text-yellow-400 font-semibold",
  congestion_clear:  "text-emerald-400 font-semibold",
  stop_violation:    "text-red-400 font-semibold",
  speed_violation:   "text-orange-400 font-semibold",
};

// Class emoji/label map
const CLASS_ICONS: Record<string, string> = {
  car: "🚗", truck: "🚚", bus: "🚌", motorcycle: "🏍️",
  pedestrian: "🚶", cyclist: "🚲", unknown: "❓",
};

function formatEventTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString([], {
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    });
  } catch {
    return ts.slice(11, 19);
  }
}

// ── Live events feed for the focused camera ───────────────────────────────────

function EventsFeed({ cameraId }: { cameraId: string }) {
  const [events, setEvents] = useState<TrafficEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const seenIdsRef = useRef<Set<string>>(new Set());

  // Initial fetch + reset when camera changes
  useEffect(() => {
    setEvents([]);
    setLoading(true);
    seenIdsRef.current = new Set();

    api.events.list({ camera_id: cameraId, limit: 30 })
      .then((evts) => {
        seenIdsRef.current = new Set(evts.map((e) => e.event_id));
        // API returns newest-first; keep that order (top = most recent)
        setEvents(evts.slice(0, MAX_EVENTS_DISPLAY));
      })
      .catch(() => null)
      .finally(() => setLoading(false));
  }, [cameraId]);

  // Poll for new events
  useEffect(() => {
    const t = setInterval(async () => {
      try {
        const fresh = await api.events.list({ camera_id: cameraId, limit: 20 });
        const incoming = fresh.filter((e) => !seenIdsRef.current.has(e.event_id));
        if (incoming.length > 0) {
          incoming.forEach((e) => seenIdsRef.current.add(e.event_id));
          setEvents((prev) => [...incoming, ...prev].slice(0, MAX_EVENTS_DISPLAY));
        }
      } catch { /* silent */ }
    }, EVENTS_POLL_MS);
    return () => clearInterval(t);
  }, [cameraId]);

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <div className="flex items-center gap-2">
          <Radio className="h-3.5 w-3.5 text-emerald-400 animate-pulse" />
          <span className="text-xs font-semibold text-foreground">Events</span>
        </div>
        <span className="text-[10px] text-muted-foreground">
          Live · {events.length} recent
        </span>
      </div>

      {/* Content */}
      {loading ? (
        <div className="px-4 py-6 text-center text-xs text-muted-foreground animate-pulse">
          Loading events…
        </div>
      ) : events.length === 0 ? (
        <div className="px-4 py-8 text-center text-xs text-muted-foreground">
          No events yet for this camera — events appear as detections are posted.
        </div>
      ) : (
        <div
          className="divide-y divide-border overflow-y-auto"
          style={{ maxHeight: "16rem" }}
        >
          {events.map((evt) => {
            const classCounts = (evt.metadata?.class_counts ?? {}) as Record<string, number>;
            const topClasses = Object.entries(classCounts)
              .sort((a, b) => b[1] - a[1]);
            const hasDetail = topClasses.length > 0;
            const conf = Math.round((evt.confidence as number) * 100);

            return (
              <div
                key={evt.event_id}
                className={cn(
                  "px-4 py-2.5 transition-colors hover:bg-secondary/20",
                  SEVERITY_ROW_CLS[evt.severity] ?? ""
                )}
              >
                {/* ── Row 1: timestamp · label · severity ── */}
                <div className="flex items-center gap-2 min-w-0">
                  <span className="font-mono text-[10px] text-muted-foreground/50 tabular-nums shrink-0 w-[4.5rem]">
                    {formatEventTime(evt.timestamp)}
                  </span>
                  <span
                    className={cn(
                      "flex-1 text-xs font-medium truncate",
                      EVENT_TYPE_TEXT_CLS[evt.event_type] ?? "text-foreground"
                    )}
                  >
                    {EVENT_LABELS[evt.event_type] ?? evt.event_type}
                  </span>
                  <span
                    className={cn(
                      "shrink-0 px-1.5 py-0.5 rounded border text-[9px] font-semibold uppercase",
                      SEVERITY_BADGE_CLS[evt.severity] ?? "bg-secondary text-muted-foreground border-border"
                    )}
                  >
                    {evt.severity}
                  </span>
                </div>

                {/* ── Row 2: class breakdown + confidence (detection events only) ── */}
                {hasDetail && (
                  <div className="flex items-center gap-3 mt-1 pl-[4.75rem] min-w-0">
                    <span className="flex items-center gap-2.5 flex-1 flex-wrap">
                      {topClasses.map(([cls, n]) => (
                        <span key={cls} className="flex items-center gap-0.5 text-[10px] text-muted-foreground/70">
                          <span>{CLASS_ICONS[cls] ?? "•"}</span>
                          <span className="capitalize">{cls}</span>
                          <span className="font-semibold text-foreground/80 tabular-nums ml-0.5">×{n}</span>
                        </span>
                      ))}
                    </span>
                    <span className="text-[10px] text-muted-foreground/40 tabular-nums shrink-0">
                      {conf}% conf
                    </span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function KpiStrip() {
  const [kpis, setKpis] = useState<KpisResponse | null>(null);

  useEffect(() => {
    api.metrics.kpis().then(setKpis).catch(() => null);
    const t = setInterval(() => api.metrics.kpis().then(setKpis).catch(() => null), 5000);
    return () => clearInterval(t);
  }, []);

  if (!kpis) return null;

  // Pull values from the tiles array (server-side badge format)
  function tile(key: string) {
    return kpis!.tiles?.find((t) => t.key === key)?.value ?? null;
  }

  const meanMs   = tile("latency_mean");
  const p95Ms    = tile("latency_p95");
  const samples  = tile("sample_count");
  const vehicles = tile("vehicle_count");
  const congestion = tile("congestion");

  return (
    <div className="flex flex-wrap gap-4 px-4 py-2 bg-card/50 border-b border-border text-xs text-muted-foreground">
      {meanMs != null && (
        <span>
          Latency avg:{" "}
          <span className="text-foreground font-medium">
            {typeof meanMs === "number" ? `${meanMs.toFixed(1)} ms` : String(meanMs)}
          </span>
        </span>
      )}
      {p95Ms != null && (
        <span>
          p95:{" "}
          <span className="text-foreground font-medium">
            {typeof p95Ms === "number" ? `${p95Ms.toFixed(1)} ms` : String(p95Ms)}
          </span>
        </span>
      )}
      {samples != null && (
        <span>
          Samples: <span className="text-foreground font-medium">{String(samples)}</span>
        </span>
      )}
      {vehicles != null && (
        <span>
          Vehicles:{" "}
          <span className="text-foreground font-medium">{String(vehicles)}</span>
        </span>
      )}
      {congestion === "CONGESTED" && (
        <span className="text-yellow-400 font-semibold">⚠ CONGESTED</span>
      )}
      {kpis.adapter === "mock" && (
        <span className="text-yellow-400 ml-auto">MOCK DATA</span>
      )}
    </div>
  );
}

// ── Large video feed pane for a single selected camera ────────────────────────

function VideoFeedPane({ camera }: { camera: Camera }) {
  const [src, setSrc] = useState("");
  const [err, setErr] = useState(false);
  const [now, setNow] = useState(() => new Date());
  const [showClock, setShowClock] = useState(true);
  const frameRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const clockRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const FEED_FPS = 4;

  // Snapshot refresh
  useEffect(() => {
    setErr(false);
    const refresh = () => setSrc(api.snapshotUrl(camera.id));
    refresh();
    frameRef.current = setInterval(refresh, 1000 / FEED_FPS);
    return () => { if (frameRef.current) clearInterval(frameRef.current); };
  }, [camera.id]);

  // Wall-clock tick (1 s)
  useEffect(() => {
    clockRef.current = setInterval(() => setNow(new Date()), 1000);
    return () => { if (clockRef.current) clearInterval(clockRef.current); };
  }, []);

  const timeStr = now.toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  });
  const dateStr = now.toLocaleDateString([], {
    weekday: "short", year: "numeric", month: "short", day: "numeric",
  });

  return (
    <div className="rounded-lg border border-border overflow-hidden bg-card">
      {/* Header bar */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border gap-2">
        {/* Left: camera name + source badge */}
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xs font-medium text-foreground truncate">{camera.name || camera.id}</span>
          <CameraSourceBadge camera={camera} />
        </div>

        {/* Right: live clock + toggle + detail link */}
        <div className="flex items-center gap-2 shrink-0">
          {/* Time + date — shown when clock is enabled */}
          {showClock && (
            <div className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse shrink-0" />
              <span className="font-mono text-xs font-bold text-foreground tabular-nums tracking-wide">
                {timeStr}
              </span>
              <span className="font-mono text-[10px] text-muted-foreground tabular-nums hidden sm:inline">
                {dateStr}
              </span>
            </div>
          )}

          {/* Clock toggle */}
          <button
            type="button"
            onClick={() => setShowClock((v) => !v)}
            title={showClock ? "Hide clock" : "Show clock"}
            className={cn(
              "flex items-center rounded p-1 transition-colors",
              showClock
                ? "text-emerald-400 hover:text-emerald-300"
                : "text-muted-foreground/40 hover:text-muted-foreground"
            )}
          >
            <Clock className="h-3.5 w-3.5" />
          </button>

          <Link
            to={`/live/${camera.id}`}
            className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
          >
            <Maximize2 className="h-3 w-3" />
            Detail
          </Link>
        </div>
      </div>

      {/* Video area */}
      <div className="relative bg-black aspect-video w-full">
        {err ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground gap-2">
            <WifiOff className="h-6 w-6" />
            <span className="text-xs">
              {camera.synthetic ? "No synthetic feed yet" : "No video signal from camera"}
            </span>
            <span className="text-[10px] text-muted-foreground/60">
              {camera.synthetic
                ? "Pipeline may be starting — wait a moment"
                : `Check that ${camera.rtsp_url || "the camera"} is reachable`}
            </span>
          </div>
        ) : (
          <img
            src={src}
            alt={`Feed: ${camera.name}`}
            className="absolute inset-0 w-full h-full object-contain"
            onError={() => setErr(true)}
            onLoad={() => setErr(false)}
          />
        )}
      </div>
    </div>
  );
}

// ── Root page ─────────────────────────────────────────────────────────────────

export function LiveWall() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [loading, setLoading] = useState(true);
  const [isMock, setIsMock] = useState(false);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  useEffect(() => {
    api.cameras.list().then((cams) => {
      setCameras(cams);
      if (cams.length > 0 && !focusId) setFocusId(cams[0].id);
      setLoading(false);
    }).catch(() => setLoading(false));
    api.metrics.kpis().then((k) => setIsMock(k.adapter === "mock" || (k as unknown as Record<string,unknown>).data_source === "mock")).catch(() => null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const focusedCamera = cameras.find((c) => c.id === focusId) ?? null;

  return (
    <div className="space-y-0">
      {/* Pipeline status bar — always visible at the top */}
      <PipelineStatusBar />

      <div className="p-4 space-y-4">
        {isMock && <CredibilityBanner />}
        <KpiStrip />

        <div className="flex items-center justify-between flex-wrap gap-2">
          <h1 className="text-lg font-semibold">Live Wall</h1>
          <div className="flex items-center gap-2">
            {/* Camera selector dropdown */}
            {cameras.length > 0 && (
              <div className="relative">
                <button
                  onClick={() => setPickerOpen(v => !v)}
                  className="flex items-center gap-1.5 rounded border border-border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors"
                >
                  {focusedCamera ? (
                    <>
                      <CameraSourceBadge camera={focusedCamera} />
                      <span className="font-medium text-foreground">{focusedCamera.name || focusedCamera.id}</span>
                    </>
                  ) : "Select camera"}
                  <ChevronDown className="h-3 w-3 ml-1" />
                </button>
                {pickerOpen && (
                  <div className="absolute right-0 top-full mt-1 z-20 w-56 rounded-lg border border-border bg-card shadow-lg overflow-hidden">
                    {cameras.map(cam => (
                      <button
                        key={cam.id}
                        onClick={() => { setFocusId(cam.id); setPickerOpen(false); }}
                        className={cn(
                          "w-full text-left flex items-center gap-2 px-3 py-2 text-xs transition-colors",
                          cam.id === focusId
                            ? "bg-primary/10 text-primary font-medium"
                            : "text-muted-foreground hover:bg-secondary hover:text-foreground"
                        )}
                      >
                        <CameraSourceBadge camera={cam} />
                        <span className="truncate">{cam.name || cam.id}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            <span className="text-xs text-muted-foreground">
              {cameras.length} camera{cameras.length !== 1 ? "s" : ""}
            </span>
          </div>
        </div>

        {loading && (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-40 rounded-lg snapshot-shimmer" />
            ))}
          </div>
        )}

        {!loading && cameras.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20 text-muted-foreground gap-2">
            <WifiOff className="h-8 w-8" />
            <p className="text-sm">No cameras configured.</p>
            <p className="text-xs">
              Go to <Link to="/studio" className="text-primary underline underline-offset-2">Studio → Camera Config</Link> to add one.
            </p>
          </div>
        )}

        {!loading && cameras.length > 0 && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Video pane + live events for focused camera */}
            <div className="lg:col-span-2 space-y-4">
              {focusedCamera && <VideoFeedPane camera={focusedCamera} />}
              {focusedCamera && <EventsFeed cameraId={focusedCamera.id} />}
            </div>

            {/* Camera picker sidebar */}
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Cameras
              </p>
              <div className="grid grid-cols-1 gap-2">
                {cameras.map((cam) => (
                  <div
                    key={cam.id}
                    onClick={() => setFocusId(cam.id)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={e => e.key === "Enter" && setFocusId(cam.id)}
                    className={cn(
                      "rounded-lg border overflow-hidden cursor-pointer transition-colors",
                      cam.id === focusId
                        ? "border-primary/60 ring-1 ring-primary/30"
                        : "border-border hover:border-primary/40"
                    )}
                  >
                    <SnapshotTile camera={cam} compact />
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Demo tile when no cameras */}
        {!loading && cameras.length === 0 && (
          <div className="mt-4">
            <p className="text-xs text-muted-foreground mb-2">Snapshot endpoint demo (mock):</p>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {["demo-cam-1", "demo-cam-2"].map((id) => (
                <SnapshotTile key={id} camera={{ id, name: id, profile: "mock", rtsp_url: "", detection_adapter: "mock", synthetic: true, enabled: true }} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
