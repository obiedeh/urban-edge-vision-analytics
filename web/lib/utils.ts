import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatTs(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  return d.toLocaleString([], { hour12: false });
}

export function relativeAge(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  return formatSeconds(diffMs / 1000) + " ago";
}

/** 3.2 → "3.2s", 95 → "1m 35s", 4000 → "1h 6m" */
export function formatSeconds(s: number | null | undefined): string {
  if (s === null || s === undefined || isNaN(s)) return "—";
  if (s < 0) s = 0;
  if (s < 10) return `${s.toFixed(1)}s`;
  if (s < 60) return `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${Math.round(s - m * 60)}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m - h * 60}m`;
}

export function formatMs(ms: number | null | undefined, digits = 0): string {
  if (ms === null || ms === undefined || isNaN(ms)) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${ms.toFixed(digits)} ms`;
}

export function formatGb(gb: number | null | undefined): string {
  if (gb === null || gb === undefined) return "—";
  return `${gb.toFixed(1)} GB`;
}

export function epochAge(epochSeconds: number | null | undefined): string {
  if (!epochSeconds) return "—";
  return formatSeconds(Date.now() / 1000 - epochSeconds) + " ago";
}

export const inputCls =
  "w-full rounded border border-input bg-background px-2 py-1.5 text-xs text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50 disabled:opacity-50";
export const selectCls =
  "w-full rounded border border-input bg-background px-2 py-1.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50 disabled:opacity-50";
export const btnPrimary =
  "inline-flex items-center gap-1.5 rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors";
export const btnGhost =
  "inline-flex items-center gap-1.5 rounded border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground hover:border-primary/40 disabled:opacity-50 disabled:cursor-not-allowed transition-colors";
export const btnDanger =
  "inline-flex items-center gap-1.5 rounded border border-red-500/40 bg-red-500/10 px-3 py-1.5 text-xs font-medium text-red-400 hover:bg-red-500/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors";
