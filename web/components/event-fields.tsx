import type { TrafficEvent } from "@/lib/api";
import { cn } from "@/lib/utils";

export const EVENT_LABELS: Record<string, string> = {
  vehicle_detected:     "Moving object detected",
  scene_clear:          "Scene clear",
  congestion_onset:     "Congestion onset",
  congestion_clear:     "Congestion cleared",
  red_light_violation:  "Red-light violation",
  unsafe_turn:          "Unsafe turn",
  wrong_way:            "Wrong-way",
  person_activity:      "Person activity",
  speed_violation:      "Speed violation",
  stop_sign_violation:  "Stop-sign compliance",
};

export const PACK_LABELS: Record<string, string> = {
  moving_object: "Moving Object",
  speed_violation: "Speed Violation",
  stop_sign: "Stop Sign",
};

export function eventLabel(evt: TrafficEvent): string {
  return EVENT_LABELS[evt.event_type] ?? evt.event_type;
}

const DECISION_CLS: Record<string, string> = {
  compliant:    "text-emerald-400 border-emerald-500/30 bg-emerald-500/10",
  rolling_stop: "text-yellow-400 border-yellow-500/30 bg-yellow-500/10",
  no_stop:      "text-red-400 border-red-500/30 bg-red-500/10",
};

function Kv({ k, v, className }: { k: string; v: React.ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-baseline gap-1 text-[11px]", className)}>
      <span className="text-muted-foreground/70">{k}</span>
      <span className="font-mono text-foreground/90 tabular-nums">{v}</span>
    </span>
  );
}

/**
 * Render the pack-specific fields of an event in one line.
 * - stop_sign: decision chip + dwell + min speed in zone
 * - speed_violation: measured vs posted + exceedance
 * - moving_object: person descriptor + direction
 * Fallback: class counts / vehicle count when present.
 */
export function EventPackFields({ evt: raw, className }: { evt: TrafficEvent; className?: string }) {
  // Live pack events carry their fields at the top level; externally ingested events may
  // only have them in metadata. Look in both.
  const evt: TrafficEvent = { ...(raw.metadata as Partial<TrafficEvent> ?? {}), ...raw } as TrafficEvent;
  const parts: React.ReactNode[] = [];

  if (evt.decision) {
    parts.push(
      <span key="decision" className={cn("inline-flex items-center px-1.5 py-0.5 rounded border text-[10px] font-semibold uppercase", DECISION_CLS[evt.decision] ?? "")}>
        {evt.decision.replace("_", " ")}
      </span>
    );
  }
  if (typeof evt.dwell_ms === "number") parts.push(<Kv key="dwell" k="dwell" v={`${(evt.dwell_ms / 1000).toFixed(1)}s`} />);
  if (typeof evt.min_speed_in_zone === "number") parts.push(<Kv key="minspd" k="min speed" v={evt.min_speed_in_zone.toFixed(3)} />);

  if (typeof evt.measured_speed === "number") {
    const unit = evt.unit ?? "kph";
    parts.push(
      <Kv
        key="speed"
        k="measured"
        v={<span className={typeof evt.posted_speed === "number" && evt.measured_speed > evt.posted_speed ? "text-orange-400 font-semibold" : ""}>{evt.measured_speed.toFixed(1)} {unit}</span>}
      />
    );
    if (typeof evt.posted_speed === "number") parts.push(<Kv key="posted" k="posted" v={`${evt.posted_speed.toFixed(0)} ${unit}`} />);
    if (typeof evt.exceedance === "number") parts.push(<Kv key="exc" k="over by" v={`${evt.exceedance > 0 ? "+" : ""}${evt.exceedance.toFixed(1)} ${unit}`} />);
  }

  if (evt.person_descriptor) parts.push(<Kv key="person" k="person" v={evt.person_descriptor} />);
  if (evt.vehicle_descriptor) parts.push(<Kv key="veh" k="vehicle" v={evt.vehicle_descriptor} />);
  const dir = typeof evt.direction === "string" ? evt.direction : evt.direction?.compass;
  if (dir) parts.push(<Kv key="dir" k="dir" v={dir} />);
  if (evt.track_id) parts.push(<Kv key="track" k="track" v={evt.track_id} />);

  if (parts.length === 0) {
    const classCounts = (evt.metadata?.class_counts ?? null) as Record<string, number> | null;
    if (classCounts && Object.keys(classCounts).length > 0) {
      parts.push(
        <span key="classes" className="text-[11px] text-muted-foreground/80">
          {Object.entries(classCounts).sort((a, b) => b[1] - a[1]).map(([c, n]) => `${c}×${n}`).join("  ")}
        </span>
      );
    } else if (typeof evt.vehicle_count === "number" && evt.vehicle_count > 0) {
      parts.push(<Kv key="count" k="objects" v={evt.vehicle_count} />);
    }
  }

  if (parts.length === 0) return null;
  return <div className={cn("flex items-center gap-3 flex-wrap", className)}>{parts}</div>;
}
