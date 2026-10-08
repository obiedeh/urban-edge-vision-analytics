import { cn } from "@/lib/utils";
import type { CameraState, ModelStatus, ReviewStatus } from "@/lib/api";
import { Wifi, WifiOff, AlertTriangle, Loader2, Square, RefreshCw } from "lucide-react";

const CAMERA_STATE_CLS: Record<CameraState, string> = {
  ended:        "bg-sky-500/15 text-sky-300 border-sky-500/30",
  streaming:    "bg-emerald-500/20 text-emerald-400 border-emerald-500/40",
  starting:     "bg-blue-500/15 text-blue-300 border-blue-500/30",
  connecting:   "bg-blue-500/15 text-blue-300 border-blue-500/30",
  reconnecting: "bg-yellow-500/20 text-yellow-400 border-yellow-500/40",
  error:        "bg-red-500/20 text-red-400 border-red-500/40",
  stopped:      "bg-secondary text-muted-foreground border-border",
};

export function CameraStateChip({
  state,
  className,
}: {
  state: CameraState | null | undefined;
  className?: string;
}) {
  const s: CameraState = state ?? "stopped";
  const Icon =
    s === "streaming" ? Wifi
    : s === "error" ? WifiOff
    : s === "reconnecting" ? RefreshCw
    : s === "stopped" || s === "ended" ? Square
    : Loader2;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold border uppercase tracking-wide",
        CAMERA_STATE_CLS[s],
        className
      )}
    >
      <Icon className={cn("h-3 w-3", (s === "starting" || s === "connecting") && "animate-spin")} />
      {state ?? "not running"}
    </span>
  );
}

export function ModelStateChip({ model, className }: { model: ModelStatus | null | undefined; className?: string }) {
  if (!model) {
    return (
      <span className={cn("inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold border bg-secondary text-muted-foreground border-border", className)}>
        MODEL —
      </span>
    );
  }
  const cls =
    model.state === "healthy" ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/40"
    : model.state === "unavailable" ? "bg-red-500/20 text-red-400 border-red-500/40"
    : "bg-secondary text-muted-foreground border-border";
  return (
    <span
      title={model.last_error ?? undefined}
      className={cn("inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold border uppercase tracking-wide", cls, className)}
    >
      {model.state === "unavailable" && <AlertTriangle className="h-3 w-3" />}
      {model.state}
    </span>
  );
}

export function SeverityChip({ severity, className }: { severity: string; className?: string }) {
  const cls: Record<string, string> = {
    info:     "bg-blue-500/10 text-blue-400 border-blue-500/20",
    warning:  "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
    critical: "bg-red-500/10 text-red-400 border-red-500/20",
  };
  return (
    <span className={cn("inline-flex items-center px-1.5 py-0.5 rounded border text-[9px] font-semibold uppercase", cls[severity] ?? "bg-secondary text-muted-foreground border-border", className)}>
      {severity}
    </span>
  );
}

export function ReviewChip({ status, className }: { status: ReviewStatus | undefined; className?: string }) {
  if (!status || status === "none") return null;
  const cls: Record<string, string> = {
    pending:   "bg-yellow-500/10 text-yellow-400 border-yellow-500/30",
    confirmed: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
    dismissed: "bg-secondary text-muted-foreground border-border",
  };
  return (
    <span className={cn("inline-flex items-center px-1.5 py-0.5 rounded border text-[9px] font-semibold uppercase", cls[status], className)}>
      review: {status}
    </span>
  );
}

const PROFILE_LABELS: Record<string, string> = {
  synthetic: "SYNTHETIC",
  browser_webrtc: "BROWSER CAM",
  rtsp_url: "RTSP LINK",
  usb: "USB",
  uploaded_video: "UPLOAD",
  generic_rtsp: "RTSP",
  http_mjpeg: "MJPEG",
  unifi_protect: "UNIFI",
};

export function ProfileChip({ profile, className }: { profile: string; className?: string }) {
  const cls =
    profile === "synthetic" ? "bg-yellow-500/15 text-yellow-400 border-yellow-500/30"
    : profile === "browser_webrtc" ? "bg-purple-500/15 text-purple-300 border-purple-500/30"
    : profile === "uploaded_video" ? "bg-sky-500/15 text-sky-300 border-sky-500/30"
    : profile === "usb" ? "bg-teal-500/15 text-teal-300 border-teal-500/30"
    : "bg-emerald-500/10 text-emerald-400 border-emerald-500/30";
  const label = PROFILE_LABELS[profile] ?? profile.toUpperCase();
  return (
    <span className={cn("inline-flex items-center px-1 py-0.5 rounded border text-[9px] font-semibold", cls, className)}>
      {label}
    </span>
  );
}

export function StatusMsg({ kind, text, className }: { kind: "ok" | "err" | "warn"; text: string; className?: string }) {
  const styles = {
    ok:   "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
    err:  "bg-red-500/10 text-red-400 border-red-500/30",
    warn: "bg-yellow-500/10 text-yellow-400 border-yellow-500/30",
  }[kind];
  return (
    <div className={cn("flex items-start gap-2 rounded px-3 py-2 text-xs border break-words", styles, className)}>
      <AlertTriangle className={cn("h-3.5 w-3.5 shrink-0 mt-0.5", kind === "ok" && "hidden")} />
      <span>{text}</span>
    </div>
  );
}
