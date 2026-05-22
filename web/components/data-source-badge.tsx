import { cn } from "@/lib/utils";

export type DataSource = "mock" | "live-rtsp" | "validated-benchmark";

const MOCK_TOOLTIP =
  "Mock adapter — does not prove real camera accuracy, Jetson latency, TensorRT acceleration, or automated enforcement readiness.";

interface Props {
  source: DataSource;
  tooltip?: string;
  className?: string;
}

const labelMap: Record<DataSource, string> = {
  mock:                 "MOCK",
  "live-rtsp":          "LIVE",
  "validated-benchmark": "BENCHMARK",
};

/**
 * Three visually distinct variants per brief §2.3:
 *
 * mock               — muted, dotted border, reduced opacity  (data is not real)
 * live-rtsp          — default emerald, solid border          (live camera feed)
 * validated-benchmark — bold blue, solid + shadow             (artifact-backed)
 */
const variantMap: Record<DataSource, string> = {
  mock: [
    "border-dashed border-yellow-500/30",
    "bg-yellow-500/10 text-yellow-400/70",
    "opacity-80",
  ].join(" "),
  "live-rtsp": [
    "border-emerald-500/40",
    "bg-emerald-500/20 text-emerald-400",
  ].join(" "),
  "validated-benchmark": [
    "border-blue-500/60",
    "bg-blue-500/20 text-blue-300",
    "shadow-sm shadow-blue-500/20 font-bold",
  ].join(" "),
};

export function DataSourceBadge({ source, tooltip, className }: Props) {
  const tip = source === "mock" ? MOCK_TOOLTIP : tooltip;
  return (
    <span
      title={tip}
      className={cn(
        "inline-flex items-center px-1.5 py-0.5 rounded text-[10px] tracking-wide border cursor-default select-none",
        variantMap[source],
        className
      )}
    >
      {labelMap[source]}
    </span>
  );
}
