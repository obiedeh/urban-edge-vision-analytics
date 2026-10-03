import { useEffect, useMemo, useState } from "react";
import { api, apiErrorMessage, type Camera, type ReviewQueue, type TrafficEvent } from "@/lib/api";
import { EventPackFields, PACK_LABELS, eventLabel } from "@/components/event-fields";
import { SeverityChip, StatusMsg } from "@/components/status-chip";
import { EventDrawer } from "@/app/pages/events";
import { cn, formatDateTime, inputCls, btnGhost } from "@/lib/utils";
import { Check, X, Undo2, Loader2, ClipboardCheck, ImageOff } from "lucide-react";

type Tab = "pending" | "confirmed" | "dismissed";
const POLL_MS = 5000;

function ReviewItem({
  evt, tab, cameraName, onReviewed, onOpen,
}: {
  evt: TrafficEvent;
  tab: Tab;
  cameraName?: string;
  onReviewed: (updated: TrafficEvent) => void;
  onOpen: () => void;
}) {
  const [note, setNote] = useState(evt.review_note ?? "");
  const [groundTruth, setGroundTruth] = useState(evt.ground_truth ?? "");
  const [busy, setBusy] = useState<"" | "confirmed" | "dismissed" | "pending">("");
  const [err, setErr] = useState<string | null>(null);

  async function act(status: "confirmed" | "dismissed" | "pending") {
    setBusy(status); setErr(null);
    // ground_truth is always sent: "" clears a previously stored value.
    try { onReviewed(await api.events.review(evt.event_id, status, note, groundTruth)); }
    catch (e) { setErr(apiErrorMessage(e, "Review failed")); }
    finally { setBusy(""); }
  }

  return (
    <div className={cn("rounded-lg border bg-card p-3 space-y-2", evt.severity === "critical" ? "border-red-500/40" : "border-border")}>
      <div className="flex items-start gap-3">
        {/* The inference frame stored when the pack emitted the event; older events have none. */}
        {evt.has_frame ? (
          <a href={api.events.frameUrl(evt.event_id)} target="_blank" rel="noreferrer" className="hidden sm:block h-16 w-24 shrink-0 overflow-hidden rounded border border-border bg-black">
            <img src={api.events.frameUrl(evt.event_id)} alt="evidence frame" className="h-full w-full object-cover" />
          </a>
        ) : (
          <div className="hidden sm:flex h-16 w-24 shrink-0 items-center justify-center rounded border border-dashed border-border bg-secondary/20 text-[9px] text-muted-foreground/60 text-center px-1">
            <span><ImageOff className="h-3 w-3 mx-auto mb-0.5" />no frame stored</span>
          </div>
        )}
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <button onClick={onOpen} className="text-xs font-semibold text-foreground hover:text-primary">{eventLabel(evt)}</button>
            <SeverityChip severity={evt.severity} />
            {evt.pack_id && <span className="rounded border border-border bg-secondary/40 px-1 text-[9px] font-mono text-muted-foreground">{PACK_LABELS[evt.pack_id] ?? evt.pack_id}</span>}
            <span className="text-[10px] text-muted-foreground ml-auto">{cameraName ?? evt.camera_id} · {formatDateTime(evt.timestamp)}</span>
          </div>
          <EventPackFields evt={evt} />
          {evt.vlm_summary && <p className="text-[11px] text-muted-foreground/80">{evt.vlm_summary}</p>}
          {evt.reviewed_at && tab !== "pending" && (
            <p className="text-[10px] text-muted-foreground/70">reviewed {formatDateTime(evt.reviewed_at)}{evt.review_note ? ` — "${evt.review_note}"` : ""}</p>
          )}
          {evt.ground_truth && (
            <p className="text-[10px] text-sky-300/90"><span className="text-muted-foreground/70">ground truth</span> {evt.ground_truth}</p>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional note" className={cn(inputCls, "flex-1 min-w-[160px]")} disabled={busy !== ""} />
        <input value={groundTruth} onChange={(e) => setGroundTruth(e.target.value)} placeholder="known pass, e.g. my car, 20 mph / full stop / rolling stop" title="Ground truth: what actually happened in this pass" className={cn(inputCls, "flex-1 min-w-[200px]")} disabled={busy !== ""} />
        {tab !== "confirmed" && (
          <button onClick={() => act("confirmed")} disabled={busy !== ""} className="inline-flex items-center gap-1 rounded border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-50">
            {busy === "confirmed" ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />} Confirm
          </button>
        )}
        {tab !== "dismissed" && (
          <button onClick={() => act("dismissed")} disabled={busy !== ""} className="inline-flex items-center gap-1 rounded border border-border bg-secondary/40 px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground disabled:opacity-50">
            {busy === "dismissed" ? <Loader2 className="h-3 w-3 animate-spin" /> : <X className="h-3 w-3" />} Dismiss
          </button>
        )}
        {tab !== "pending" && (
          <button onClick={() => act("pending")} disabled={busy !== ""} className={btnGhost} title="Move back to the pending queue">
            {busy === "pending" ? <Loader2 className="h-3 w-3 animate-spin" /> : <Undo2 className="h-3 w-3" />} Reopen
          </button>
        )}
      </div>
      {err && <StatusMsg kind="err" text={err} />}
    </div>
  );
}

export function ReviewPage() {
  const [tab, setTab] = useState<Tab>("pending");
  const [queue, setQueue] = useState<ReviewQueue | null>(null);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<TrafficEvent | null>(null);

  useEffect(() => { api.cameras.list().then(setCameras).catch(() => null); }, []);
  const camName = useMemo(() => new Map(cameras.map((c) => [c.id, c.name])), [cameras]);

  useEffect(() => {
    let dead = false;
    const load = async () => {
      try { const q = await api.events.reviewQueue(tab); if (!dead) { setQueue(q); setError(null); } }
      catch (e) { if (!dead) setError(apiErrorMessage(e, "Could not load review queue")); }
    };
    load();
    const t = setInterval(load, POLL_MS);
    return () => { dead = true; clearInterval(t); };
  }, [tab]);

  function onReviewed(updated: TrafficEvent) {
    setQueue((q) => {
      if (!q) return q;
      const counts = { ...q.counts };
      const prev = q.events.find((e) => e.event_id === updated.event_id);
      const from = (prev?.review_status ?? tab) as Tab;
      const to = updated.review_status as Tab;
      if (from in counts) counts[from] = Math.max(0, counts[from] - 1);
      if (to in counts) counts[to] = counts[to] + 1;
      return { counts, events: to === tab ? q.events.map((e) => (e.event_id === updated.event_id ? updated : e)) : q.events.filter((e) => e.event_id !== updated.event_id) };
    });
  }

  const counts = queue?.counts ?? { pending: 0, confirmed: 0, dismissed: 0 };

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <ClipboardCheck className="h-4 w-4 text-muted-foreground" />
          <h1 className="text-lg font-semibold">Review queue</h1>
        </div>
        <div className="flex items-center gap-1">
          {(["pending", "confirmed", "dismissed"] as Tab[]).map((t) => (
            <button key={t} onClick={() => setTab(t)} className={cn("flex items-center gap-1.5 rounded border px-3 py-1 text-xs capitalize transition-colors", tab === t ? "border-primary/60 bg-primary/15 text-foreground" : "border-border text-muted-foreground hover:text-foreground")}>
              {t}
              <span className={cn("rounded-full px-1.5 text-[10px] tabular-nums", t === "pending" && counts.pending > 0 ? "bg-yellow-500/20 text-yellow-300" : "bg-secondary text-muted-foreground")}>{counts[t]}</span>
            </button>
          ))}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">Events the packs flagged for operator review (critical severity is always flagged). Confirm or dismiss with an optional note; items move between tabs.</p>

      {error && <StatusMsg kind="err" text={error} />}

      {!queue && !error && <div className="space-y-2">{[...Array(3)].map((_, i) => <div key={i} className="h-24 rounded-lg snapshot-shimmer" />)}</div>}
      {queue && queue.events.length === 0 && (
        <div className="py-12 text-center text-sm text-muted-foreground">Nothing {tab}.</div>
      )}
      <div className="space-y-2">
        {queue?.events.map((evt) => (
          <ReviewItem key={evt.event_id} evt={evt} tab={tab} cameraName={camName.get(evt.camera_id)} onReviewed={onReviewed} onOpen={() => setOpen(evt)} />
        ))}
      </div>

      {open && <EventDrawer event={open} cameraName={camName.get(open.camera_id)} onClose={() => setOpen(null)} />}
    </div>
  );
}
