import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Camera, type KpisResponse } from "@/lib/api";
import { CredibilityBanner } from "@/components/credibility-banner";
import { cn } from "@/lib/utils";
import { Wifi, WifiOff, AlertTriangle } from "lucide-react";

const GRID_FPS = 1;
const STALE_WARN_MS = 10_000;
const STALE_OFFLINE_MS = 30_000;

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

function SnapshotTile({ camera }: { camera: Camera }) {
  const [src, setSrc] = useState<string>("");
  const [lastAt, setLastAt] = useState<number | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    function refresh() {
      setSrc(api.snapshotUrl(camera.id));
      setLastAt(Date.now());
    }
    refresh();
    intervalRef.current = setInterval(refresh, 1000 / GRID_FPS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [camera.id]);

  const status = cameraStatus(lastAt);

  return (
    <Link
      to={`/live/${camera.id}`}
      className="group relative block rounded-lg border border-border overflow-hidden bg-card hover:border-primary/50 transition-colors"
    >
      {src ? (
        <img
          src={src}
          alt={`Camera ${camera.name}`}
          className="w-full h-40 object-cover"
          onError={() => setLastAt(null)}
        />
      ) : (
        <div className="w-full h-40 snapshot-shimmer" />
      )}
      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-background/90 to-transparent px-3 py-2 flex items-center justify-between">
        <span className="text-xs font-medium text-foreground truncate">{camera.name}</span>
        <StatusBadge status={status} />
      </div>
    </Link>
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

export function LiveWall() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [loading, setLoading] = useState(true);
  const [isMock, setIsMock] = useState(false);

  useEffect(() => {
    api.cameras.list().then((cams) => {
      setCameras(cams);
      setLoading(false);
    }).catch(() => setLoading(false));
    api.metrics.kpis().then((k) => setIsMock(k.adapter === "mock" || (k as unknown as Record<string,unknown>).data_source === "mock")).catch(() => null);
  }, []);

  return (
    <div className="p-4 space-y-4">
      {isMock && <CredibilityBanner />}
      <KpiStrip />
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Live Wall</h1>
        <span className="text-xs text-muted-foreground">{cameras.length} camera{cameras.length !== 1 ? "s" : ""}</span>
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
          <p className="text-xs">Add cameras via <code className="text-primary">configs/camera.local.json</code> or the API.</p>
        </div>
      )}

      {!loading && cameras.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {cameras.map((cam) => (
            <SnapshotTile key={cam.id} camera={cam} />
          ))}
        </div>
      )}

      {/* Demo tile when no cameras — shows snapshot endpoint works */}
      {!loading && cameras.length === 0 && (
        <div className="mt-4">
          <p className="text-xs text-muted-foreground mb-2">Snapshot endpoint demo (mock):</p>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {["demo-cam-1", "demo-cam-2"].map((id) => (
              <SnapshotTile key={id} camera={{ id, name: id, profile: "mock", rtsp_url: "", detection_adapter: "mock", enabled: true }} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
