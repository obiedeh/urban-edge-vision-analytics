import { cn } from "@/lib/utils";
import type { SourceKind } from "@/lib/api";

/**
 * Where the frames behind a camera, event, live result or run came from.
 * Live kinds are green; uploaded and synthetic footage is visibly different
 * so recorded or generated evidence is never read as a live camera.
 */
const LABEL: Record<SourceKind, string> = {
  live_rtsp: "LIVE",
  usb: "USB LIVE",
  browser: "BROWSER LIVE",
  uploaded_recorded: "UPLOADED · RECORDED",
  uploaded_generated: "UPLOADED · GENERATED",
  synthetic: "SYNTHETIC",
};

const TIP: Record<SourceKind, string> = {
  live_rtsp: "Live network camera (RTSP, RTSPS or HTTP MJPEG).",
  usb: "Live USB camera attached to this device.",
  browser: "Live camera shared from an operator's browser.",
  uploaded_recorded: "Uploaded recording of a real scene. Not a live camera.",
  uploaded_generated: "Uploaded generated footage (simulation, text-to-video). Not a live camera.",
  synthetic: "Built-in synthetic test pattern. Not a live camera.",
};

const CLS: Record<SourceKind, string> = {
  live_rtsp: "bg-emerald-500/15 text-emerald-400 border-emerald-500/40",
  usb: "bg-emerald-500/15 text-emerald-400 border-emerald-500/40",
  browser: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
  uploaded_recorded: "bg-sky-500/15 text-sky-300 border-sky-500/40",
  uploaded_generated: "bg-orange-500/15 text-orange-300 border-orange-500/50",
  synthetic: "bg-yellow-500/15 text-yellow-400 border-yellow-500/40 border-dashed",
};

export function isLiveSource(kind: SourceKind | null | undefined): boolean {
  return kind === "live_rtsp" || kind === "usb" || kind === "browser";
}

export function SourceKindBadge({ kind, className, size = "xs" }: { kind: SourceKind | null | undefined; className?: string; size?: "xs" | "sm" }) {
  if (!kind || !(kind in LABEL)) return null;
  return (
    <span
      title={TIP[kind]}
      className={cn(
        "inline-flex items-center rounded border font-semibold tracking-wide select-none",
        size === "xs" ? "px-1 py-0.5 text-[9px]" : "px-1.5 py-0.5 text-[10px]",
        CLS[kind],
        className
      )}
    >
      {LABEL[kind]}
    </span>
  );
}

/** Sentence shown next to evidence from non-live sources. */
export function evidenceNote(kind: SourceKind | null | undefined): string | null {
  if (!kind || isLiveSource(kind)) return null;
  return TIP[kind];
}
