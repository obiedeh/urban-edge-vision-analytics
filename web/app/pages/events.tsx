import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, apiErrorMessage, type Camera, type ReviewStatus, type TrafficEvent } from "@/lib/api";
import { EventPackFields, EVENT_LABELS, PACK_LABELS, eventLabel } from "@/components/event-fields";
import { ReviewChip, SeverityChip, StatusMsg } from "@/components/status-chip";
import { SourceKindBadge, evidenceNote } from "@/components/source-kind-badge";
import { cn, formatDateTime, formatTs, selectCls, btnGhost } from "@/lib/utils";
import { X, RefreshCw } from "lucide-react";

const ALL = "";
const PAGE = 50;
const POLL_MS = 3000;

export function EventDrawer({ event, onClose, cameraName }: { event: TrafficEvent; onClose: () => void; cameraName?: string }) {
  const { metadata, ...rest } = event;
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-[560px] max-w-full bg-card border-l border-border flex flex-col overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-4 py-3 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm font-semibold text-foreground truncate">{eventLabel(event)}</span>
            <SeverityChip severity={event.severity} />
            <ReviewChip status={event.review_status} />
            <SourceKindBadge kind={event.source_kind} />
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground"><X className="h-4 w-4" /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
          <div className="grid grid-cols-2 gap-x-4 gap-y-2">
            <div><div className="text-muted-foreground">Camera</div><div className="font-mono text-foreground">{cameraName ?? event.camera_id}{cameraName ? <span className="text-muted-foreground/60"> · {event.camera_id}</span> : null}</div></div>
            <div><div className="text-muted-foreground">Time</div><div className="text-foreground">{formatDateTime(event.timestamp)}</div></div>
            <div><div className="text-muted-foreground">Pack</div><div className="font-mono text-foreground">{event.pack_id ? PACK_LABELS[event.pack_id] ?? event.pack_id : "—"}</div></div>
            <div><div className="text-muted-foreground">Confidence</div><div className="text-foreground">{(event.confidence * 100).toFixed(0)}%</div></div>
            <div><div className="text-muted-foreground">Event id</div><div className="font-mono text-foreground/80 break-all">{event.event_id}</div></div>
            {event.vlm_model && <div><div className="text-muted-foreground">Model</div><div className="font-mono text-foreground/80">{event.vlm_model}</div></div>}
            <div><div className="text-muted-foreground">Source</div><div className="text-foreground flex items-center gap-2"><SourceKindBadge kind={event.source_kind} />{!event.source_kind && <span className="text-muted-foreground/70">not recorded (older event)</span>}</div></div>
          </div>
          {event.has_frame && (
            <div className="space-y-1">
              <div className="text-muted-foreground">Evidence frame</div>
              <div className="relative rounded border border-border overflow-hidden bg-black">
                <img src={api.events.frameUrl(event.event_id)} alt="evidence frame" className="w-full max-h-72 object-contain" />
                {evidenceNote(event.source_kind) && (
                  <div className="absolute inset-x-0 bottom-0 bg-orange-950/85 text-orange-200 text-[10px] px-2 py-1 flex items-center gap-2">
                    <SourceKindBadge kind={event.source_kind} /> {evidenceNote(event.source_kind)}
                  </div>
                )}
              </div>
            </div>
          )}
          {!event.has_frame && evidenceNote(event.source_kind) && (
            <div className="rounded border border-orange-500/30 bg-orange-500/10 px-3 py-2 text-orange-200 flex items-center gap-2"><SourceKindBadge kind={event.source_kind} /> {evidenceNote(event.source_kind)}</div>
          )}
          <div>
            <div className="text-muted-foreground mb-1">Pack fields</div>
            <EventPackFields evt={event} />
          </div>
          {event.vlm_summary && (
            <div><div className="text-muted-foreground mb-1">Summary</div><p className="text-foreground">{event.vlm_summary}</p></div>
          )}
          {event.review_status && event.review_status !== "none" && (
            <div className="rounded border border-border bg-secondary/20 px-3 py-2">
              <div className="text-muted-foreground">Review</div>
              <div className="text-foreground">{event.review_status}{event.reviewed_at ? ` · ${formatDateTime(event.reviewed_at)}` : ""}</div>
              {event.review_note && <div className="text-foreground/80 mt-1 italic">"{event.review_note}"</div>}
            </div>
          )}
          {event.ground_truth && (
            <div className="rounded border border-sky-500/30 bg-sky-500/10 px-3 py-2">
              <div className="text-muted-foreground">Ground truth</div>
              <div className="text-sky-200">{event.ground_truth}</div>
            </div>
          )}
          <div>
            <div className="text-muted-foreground mb-1">Raw metadata</div>
            <pre className="text-[10px] bg-black/40 border border-border rounded p-2 overflow-x-auto text-foreground/80 whitespace-pre-wrap">{JSON.stringify(metadata ?? {}, null, 2)}</pre>
          </div>
          <div>
            <div className="text-muted-foreground mb-1">Full event</div>
            <pre className="text-[10px] bg-black/40 border border-border rounded p-2 overflow-x-auto text-foreground/60 whitespace-pre-wrap">{JSON.stringify(rest, null, 2)}</pre>
          </div>
        </div>
      </div>
    </div>
  );
}

export function EventRow({ evt, onClick, cameraName, selected }: { evt: TrafficEvent; onClick: () => void; cameraName?: string; selected?: boolean }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full text-left flex items-start gap-3 rounded-lg border bg-card px-3 py-2.5 hover:border-primary/40 transition-colors",
        selected ? "border-primary/60" : "border-border",
        evt.severity === "critical" && "border-l-2 border-l-red-500/60",
        evt.severity === "warning" && "border-l-2 border-l-yellow-500/60"
      )}
    >
      <span className="font-mono text-[10px] text-muted-foreground/70 tabular-nums shrink-0 w-[4.5rem] pt-0.5">{formatTs(evt.timestamp)}</span>
      <div className="flex-1 min-w-0 space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-medium text-foreground">{eventLabel(evt)}</span>
          <SeverityChip severity={evt.severity} />
          <ReviewChip status={evt.review_status} />
          <SourceKindBadge kind={evt.source_kind} />
          {evt.pack_id && <span className="text-[10px] text-muted-foreground font-mono">{evt.pack_id}</span>}
          <span className="text-[10px] text-muted-foreground font-mono ml-auto">{cameraName ?? evt.camera_id}</span>
        </div>
        <EventPackFields evt={evt} />
        {evt.vlm_summary && <p className="text-[11px] text-muted-foreground/80 truncate">{evt.vlm_summary}</p>}
        {evt.ground_truth && <p className="text-[10px] text-sky-300/90 truncate"><span className="text-muted-foreground/70">ground truth</span> {evt.ground_truth}</p>}
      </div>
    </button>
  );
}

export function EventsPage() {
  const [params, setParams] = useSearchParams();
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [events, setEvents] = useState<TrafficEvent[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<TrafficEvent | null>(null);
  const [loading, setLoading] = useState(true);

  const camFilter = params.get("camera_id") ?? ALL;
  const typeFilter = params.get("event_type") ?? ALL;
  const reviewFilter = (params.get("review_status") ?? ALL) as ReviewStatus | "";
  const setFilter = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v); else next.delete(k);
    next.delete("event_id");
    setParams(next, { replace: true });
  };

  useEffect(() => { api.cameras.list().then(setCameras).catch(() => null); }, []);
  const camName = useMemo(() => new Map(cameras.map((c) => [c.id, c.name])), [cameras]);

  const query = useMemo(() => ({
    camera_id: camFilter || undefined,
    event_type: typeFilter || undefined,
    review_status: reviewFilter || undefined,
  }), [camFilter, typeFilter, reviewFilter]);

  // Initial load + poll newest page; merge by event_id (review status may change).
  useEffect(() => {
    let dead = false;
    setLoading(true); setEvents([]);
    const load = async (initial: boolean) => {
      try {
        const fresh = await api.events.list({ ...query, limit: PAGE });
        if (dead) return;
        setEvents((prev) => {
          if (initial) return fresh;
          const byId = new Map(prev.map((e) => [e.event_id, e]));
          for (const e of fresh) byId.set(e.event_id, e);
          return [...byId.values()].sort((a, b) => b.timestamp.localeCompare(a.timestamp));
        });
        if (initial) setHasMore(fresh.length === PAGE);
        setError(null);
      } catch (e) { if (!dead) setError(apiErrorMessage(e, "Could not load events")); }
      finally { if (!dead) setLoading(false); }
    };
    load(true);
    const t = setInterval(() => load(false), POLL_MS);
    return () => { dead = true; clearInterval(t); };
  }, [query]);

  // Deep link ?event_id=
  const eventId = params.get("event_id");
  useEffect(() => {
    if (!eventId) return;
    const local = events.find((e) => e.event_id === eventId);
    if (local) { setSelected(local); return; }
    api.events.get(eventId).then(setSelected).catch(() => null);
  }, [eventId, events.length]); // eslint-disable-line react-hooks/exhaustive-deps

  async function loadMore() {
    const last = events[events.length - 1];
    if (!last) return;
    try {
      const older = await api.events.list({ ...query, limit: PAGE, before: last.timestamp });
      setEvents((prev) => {
        const ids = new Set(prev.map((e) => e.event_id));
        return [...prev, ...older.filter((e) => !ids.has(e.event_id))];
      });
      setHasMore(older.length === PAGE);
    } catch (e) { setError(apiErrorMessage(e)); }
  }

  const types = useMemo(() => Array.from(new Set([...Object.keys(EVENT_LABELS), ...events.map((e) => e.event_type)])), [events]);

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-lg font-semibold">Events</h1>
        <div className="flex items-center gap-2 flex-wrap">
          <select value={camFilter} onChange={(e) => setFilter("camera_id", e.target.value)} className={cn(selectCls, "w-auto")}>
            <option value={ALL}>All cameras</option>
            {cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <select value={typeFilter} onChange={(e) => setFilter("event_type", e.target.value)} className={cn(selectCls, "w-auto")}>
            <option value={ALL}>All types</option>
            {types.map((t) => <option key={t} value={t}>{EVENT_LABELS[t] ?? t}</option>)}
          </select>
          <select value={reviewFilter} onChange={(e) => setFilter("review_status", e.target.value)} className={cn(selectCls, "w-auto")}>
            <option value={ALL}>Any review status</option>
            <option value="pending">Pending review</option>
            <option value="confirmed">Confirmed</option>
            <option value="dismissed">Dismissed</option>
            <option value="none">Not flagged</option>
          </select>
          <span className="text-xs text-muted-foreground flex items-center gap-1"><RefreshCw className="h-3 w-3" /> {events.length} loaded · polling {POLL_MS / 1000}s</span>
        </div>
      </div>

      {error && <StatusMsg kind="err" text={error} />}

      <div className="space-y-1.5">
        {loading && <div className="space-y-2">{[...Array(4)].map((_, i) => <div key={i} className="h-12 rounded-lg snapshot-shimmer" />)}</div>}
        {!loading && events.length === 0 && (
          <div className="py-12 text-center text-sm text-muted-foreground">No events match the current filters. Pack events are written when an enabled pack fires on a camera.</div>
        )}
        {events.map((evt) => (
          <EventRow key={evt.event_id} evt={evt} cameraName={camName.get(evt.camera_id)} selected={selected?.event_id === evt.event_id} onClick={() => { setSelected(evt); }} />
        ))}
      </div>

      {hasMore && events.length > 0 && (
        <div className="text-center">
          <button onClick={loadMore} className={btnGhost}>Load older</button>
        </div>
      )}

      {selected && <EventDrawer event={selected} cameraName={camName.get(selected.camera_id)} onClose={() => { setSelected(null); if (eventId) setFilter("event_id", ""); }} />}
    </div>
  );
}
