import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type RuntimeStatus } from "@/lib/api";
import { CameraStateChip, ModelStateChip } from "@/components/status-chip";
import { formatMs } from "@/lib/utils";
import { Cpu, Video, AlertTriangle } from "lucide-react";

/** Poll /runtime/status at a fixed cadence and share the latest snapshot. */
export function useRuntimeStatus(pollMs = 2000) {
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let dead = false;
    const tick = async () => {
      try {
        const s = await api.runtime.status();
        if (!dead) { setStatus(s); setError(null); }
      } catch (e) {
        if (!dead) setError(e instanceof Error ? e.message : "runtime status unavailable");
      }
    };
    tick();
    const t = setInterval(tick, pollMs);
    return () => { dead = true; clearInterval(t); };
  }, [pollMs]);
  return { status, error };
}

/**
 * Compact runtime strip: model backend/health/latency on the left, per-camera
 * state chips on the right. Used on Live and Models.
 */
export function RuntimeStatusBar({ status }: { status: RuntimeStatus | null }) {
  const model = status?.model ?? null;
  const cams = status?.cameras ?? [];
  const streaming = cams.filter((c) => c.state === "streaming").length;

  return (
    <div className="border-b border-border bg-secondary/10 px-4 py-2 flex items-center gap-3 flex-wrap text-xs">
      <Cpu className="h-3.5 w-3.5 text-muted-foreground" />
      <ModelStateChip model={model} />
      {model ? (
        <>
          <span className="font-mono text-[11px] text-foreground/80 truncate max-w-[260px]" title={model.label || model.model}>
            {model.backend}{model.model ? ` · ${model.model}` : ""}
          </span>
          {model.latency?.p50_ms != null && (
            <span className="text-muted-foreground/70 text-[10px] tabular-nums">
              p50 {formatMs(model.latency.p50_ms)} · p95 {formatMs(model.latency.p95_ms)}
            </span>
          )}
          {model.total_calls > 0 && (
            <span className="text-muted-foreground/60 text-[10px] tabular-nums">
              {model.total_calls} calls · {model.total_failures} failed
            </span>
          )}
          {model.state === "unavailable" && model.last_error && (
            <span className="flex items-center gap-1 text-red-400 text-[10px] truncate max-w-[360px]" title={model.last_error}>
              <AlertTriangle className="h-3 w-3 shrink-0" /> {model.last_error}
            </span>
          )}
        </>
      ) : (
        <span className="text-muted-foreground">runtime status unavailable</span>
      )}

      <div className="ml-auto flex items-center gap-2 flex-wrap">
        <Video className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-muted-foreground/70 text-[10px]">
          {streaming}/{cams.length} streaming
        </span>
        {cams.slice(0, 6).map((c) => (
          <Link key={c.camera_id} to={`/live/${encodeURIComponent(c.camera_id)}`} title={`${c.name} · ${c.fps} fps${c.last_error ? ` · ${c.last_error}` : ""}`} className="flex items-center gap-1">
            <span className="text-[10px] text-foreground/70 max-w-[100px] truncate">{c.name}</span>
            <CameraStateChip state={c.state} />
          </Link>
        ))}
        {cams.length > 6 && <span className="text-[10px] text-muted-foreground">+{cams.length - 6}</span>}
        <Link to="/models" className="text-[10px] text-primary/80 hover:text-primary">Models</Link>
      </div>
    </div>
  );
}
