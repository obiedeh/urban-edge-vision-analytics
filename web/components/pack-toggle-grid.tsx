import { cn } from "@/lib/utils";
import type { Binding, UseCasePack } from "@/lib/api";

const PACK_LABELS: Record<string, string> = {
  moving_object: "Moving Object",
  speed_violation: "Speed Violation",
  stop_sign: "Stop Sign",
};

const PACK_DESC: Record<string, string> = {
  moving_object: "Detects persons in frame with direction & attributes",
  speed_violation: "Vehicles exceeding posted speed across two calibrated gates",
  stop_sign: "Vehicles failing to stop at a defined stop zone",
};

// Blocked combinations per the brief §11.4
const BLOCKED: Set<string> = new Set([
  "speed_violation+stop_sign",
  "stop_sign+speed_violation",
]);

function packSetKey(ids: string[]): string {
  return [...ids].sort().join("+");
}

function wouldBeBlocked(active: Set<string>, toggling: string): boolean {
  const next = new Set(active);
  if (next.has(toggling)) {
    next.delete(toggling);
  } else {
    next.add(toggling);
  }
  return BLOCKED.has(packSetKey(Array.from(next)));
}

interface Props {
  packs: UseCasePack[];
  bindings: Binding[];
  onChange: (updated: Binding[]) => void;
  disabled?: boolean;
}

export function PackToggleGrid({ packs, bindings, onChange, disabled }: Props) {
  const activePacks = new Set(
    bindings.filter((b) => b.enabled).map((b) => b.pack_id)
  );

  function toggle(packId: string) {
    const isActive = activePacks.has(packId);
    const updated: Binding[] = packs.map((p) => {
      const existing = bindings.find((b) => b.pack_id === p.pack_id);
      const enabled =
        p.pack_id === packId ? !isActive : (existing?.enabled ?? false);
      return {
        pack_id: p.pack_id,
        parameters: existing?.parameters ?? {},
        report_interval_seconds: existing?.report_interval_seconds ?? 5,
        enabled,
      };
    });
    onChange(updated);
  }

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {packs.map((p) => {
        const active = activePacks.has(p.pack_id);
        const blocked = !active && wouldBeBlocked(activePacks, p.pack_id);
        return (
          <button
            key={p.pack_id}
            disabled={disabled || blocked}
            onClick={() => toggle(p.pack_id)}
            title={
              blocked
                ? "This pack cannot be combined with your current selection (§11.4 compatibility rule)"
                : undefined
            }
            className={cn(
              "relative flex flex-col items-start gap-1 rounded-lg border px-4 py-3 text-left text-sm transition-colors",
              active
                ? "border-primary bg-primary/10 text-foreground"
                : "border-border bg-card text-muted-foreground hover:border-primary/50",
              (disabled || blocked) && "opacity-40 cursor-not-allowed"
            )}
          >
            <span className="font-semibold text-foreground">
              {PACK_LABELS[p.pack_id] ?? p.pack_id}
            </span>
            <span className="text-xs">{PACK_DESC[p.pack_id] ?? ""}</span>
            {blocked && (
              <span className="absolute top-2 right-2 text-[9px] text-yellow-400 border border-yellow-400/40 px-1 rounded">
                BLOCKED
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
