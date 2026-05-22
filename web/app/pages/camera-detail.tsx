import { useEffect, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, type TrafficEvent } from "@/lib/api";
import { useEventStream } from "@/lib/sse";
import { formatTs } from "@/lib/utils";
import { ArrowLeft, X } from "lucide-react";

const DETAIL_FPS = 5;

const severityColor: Record<string, string> = {
  info: "text-blue-400",
  warning: "text-yellow-400",
  critical: "text-red-400",
};

function EventDrawer({
  event,
  onClose,
}: {
  event: TrafficEvent;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-96 max-w-full bg-card border-l border-border p-4 flex flex-col gap-4 overflow-y-auto">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-sm">Event Detail</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-2 text-xs">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Type</span>
            <span className="font-mono text-foreground">{event.event_type}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Severity</span>
            <span className={severityColor[event.severity] ?? "text-foreground"}>
              {event.severity.toUpperCase()}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Time</span>
            <span>{formatTs(event.timestamp)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Camera</span>
            <span className="font-mono">{event.camera_id}</span>
          </div>
          {event.track_id != null && (
            <div className="flex justify-between">
              <span className="text-muted-foreground">Track</span>
              <span className="font-mono">{String(event.track_id)}</span>
            </div>
          )}
        </div>
        <div>
          <p className="text-xs text-muted-foreground mb-1">Raw payload</p>
          <pre className="text-[10px] bg-secondary/30 rounded p-2 overflow-x-auto text-foreground/80 whitespace-pre-wrap">
            {JSON.stringify(event, null, 2)}
          </pre>
        </div>
      </div>
    </div>
  );
}

export function CameraDetail() {
  const { id } = useParams<{ id: string }>();
  const cameraId = id ?? "";
  const [src, setSrc] = useState("");
  const [selected, setSelected] = useState<TrafficEvent | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const streamEvents = useEventStream(50);
  const cameraEvents = streamEvents.filter((e) => e.camera_id === cameraId);

  useEffect(() => {
    function refresh() {
      setSrc(api.snapshotUrl(cameraId));
    }
    refresh();
    intervalRef.current = setInterval(refresh, 1000 / DETAIL_FPS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [cameraId]);

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center gap-3">
        <Link
          to="/live"
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          Live Wall
        </Link>
        <h1 className="text-lg font-semibold">{cameraId}</h1>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Snapshot — 2/3 width on large screens */}
        <div className="lg:col-span-2">
          {src ? (
            <img
              src={src}
              alt={`Camera ${cameraId}`}
              className="w-full rounded-lg border border-border object-cover max-h-[480px]"
            />
          ) : (
            <div className="w-full h-64 rounded-lg snapshot-shimmer" />
          )}
        </div>

        {/* Event sidebar */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium">Live Events</h2>
            <span className="text-xs text-muted-foreground">{cameraEvents.length} events</span>
          </div>
          <div className="flex-1 overflow-y-auto max-h-[420px] space-y-1">
            {cameraEvents.length === 0 && (
              <p className="text-xs text-muted-foreground py-4 text-center">
                Waiting for events…
              </p>
            )}
            {cameraEvents.map((evt) => (
              <button
                key={evt.event_id}
                onClick={() => setSelected(evt)}
                className="w-full text-left rounded border border-border bg-card px-3 py-2 hover:border-primary/50 transition-colors"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-mono text-foreground truncate">
                    {evt.event_type}
                  </span>
                  <span className={`text-[10px] font-semibold ${severityColor[evt.severity] ?? ""}`}>
                    {evt.severity.toUpperCase()}
                  </span>
                </div>
                <div className="text-[10px] text-muted-foreground mt-0.5">
                  {formatTs(evt.timestamp)}
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>

      {selected && (
        <EventDrawer event={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
