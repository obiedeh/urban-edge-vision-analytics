import { useEffect, useState } from "react";
import { api, type TrafficEvent } from "@/lib/api";
import { useEventStream } from "@/lib/sse";
import { formatTs, cn } from "@/lib/utils";

const severityColor: Record<string, string> = {
  info: "text-blue-400 border-blue-500/30 bg-blue-500/10",
  warning: "text-yellow-400 border-yellow-500/30 bg-yellow-500/10",
  critical: "text-red-400 border-red-500/30 bg-red-500/10",
};

const ALL = "all";

export function EventFeed() {
  const [history, setHistory] = useState<TrafficEvent[]>([]);
  const [hasMore, setHasMore] = useState(true);
  const [filterCamera, setFilterCamera] = useState(ALL);
  const [filterSeverity, setFilterSeverity] = useState(ALL);
  const [filterType, setFilterType] = useState(ALL);
  const liveEvents = useEventStream(200);

  // Load initial history
  useEffect(() => {
    api.events.list({ limit: 50 }).then((evts) => {
      setHistory(evts);
      setHasMore(evts.length === 50);
    }).catch(() => null);
  }, []);

  function loadMore() {
    const last = history[history.length - 1];
    api.events.list({ cursor: last?.event_id, limit: 50 }).then((evts) => {
      setHistory((h) => [...h, ...evts]);
      setHasMore(evts.length === 50);
    }).catch(() => null);
  }

  // Merge live events into display list (dedup by event_id)
  const allEvents = [
    ...liveEvents.filter((e) => !history.some((h) => h.event_id === e.event_id)),
    ...history,
  ];

  // Unique camera IDs for filter
  const cameras = [...new Set(allEvents.map((e) => e.camera_id))];
  const types = [...new Set(allEvents.map((e) => e.event_type))];
  const severities = ["info", "warning", "critical"];

  const filtered = allEvents.filter((e) => {
    if (filterCamera !== ALL && e.camera_id !== filterCamera) return false;
    if (filterSeverity !== ALL && e.severity !== filterSeverity) return false;
    if (filterType !== ALL && e.event_type !== filterType) return false;
    return true;
  });

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-lg font-semibold">Event Feed</h1>
        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={filterCamera}
            onChange={(e) => setFilterCamera(e.target.value)}
            className="rounded border border-input bg-background px-2 py-1 text-xs text-foreground"
          >
            <option value={ALL}>All cameras</option>
            {cameras.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <select
            value={filterSeverity}
            onChange={(e) => setFilterSeverity(e.target.value)}
            className="rounded border border-input bg-background px-2 py-1 text-xs text-foreground"
          >
            <option value={ALL}>All severities</option>
            {severities.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="rounded border border-input bg-background px-2 py-1 text-xs text-foreground"
          >
            <option value={ALL}>All types</option>
            {types.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <span className="text-xs text-muted-foreground">
            {filtered.length} event{filtered.length !== 1 ? "s" : ""}
          </span>
        </div>
      </div>

      <div className="space-y-1">
        {filtered.length === 0 && (
          <div className="py-12 text-center text-sm text-muted-foreground">
            No events match the current filters.
          </div>
        )}
        {filtered.map((evt) => (
          <div
            key={evt.event_id}
            className="flex items-start gap-3 rounded-lg border border-border bg-card px-3 py-2.5"
          >
            <span
              className={cn(
                "mt-0.5 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold border shrink-0",
                severityColor[evt.severity] ?? "text-muted-foreground border-border bg-secondary/20"
              )}
            >
              {evt.severity.toUpperCase()}
            </span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs font-mono font-medium text-foreground">
                  {evt.event_type}
                </span>
                <span className="text-[10px] text-muted-foreground font-mono">
                  {evt.camera_id}
                </span>
                {evt.confidence != null && (
                  <span className="text-[10px] text-muted-foreground">
                    {(evt.confidence * 100).toFixed(0)}%
                  </span>
                )}
              </div>
              {evt.timestamp && (
                <div className="text-[10px] text-muted-foreground mt-0.5">
                  {formatTs(evt.timestamp)}
                </div>
              )}
            </div>
            <span className="text-[10px] text-muted-foreground font-mono shrink-0">
              {evt.event_id.slice(0, 8)}
            </span>
          </div>
        ))}
      </div>

      {hasMore && filtered.length > 0 && (
        <div className="text-center">
          <button
            onClick={loadMore}
            className="px-4 py-1.5 rounded border border-border text-sm text-muted-foreground hover:text-foreground hover:border-primary/50 transition-colors"
          >
            Load more
          </button>
        </div>
      )}
    </div>
  );
}
