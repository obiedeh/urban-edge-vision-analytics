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
  mock: "MOCK",
  "live-rtsp": "LIVE",
  "validated-benchmark": "BENCHMARK",
};

const colorMap: Record<DataSource, string> = {
  mock: "bg-yellow-500/20 text-yellow-400 border-yellow-500/40",
  "live-rtsp": "bg-emerald-500/20 text-emerald-400 border-emerald-500/40",
  "validated-benchmark": "bg-blue-500/20 text-blue-400 border-blue-500/40",
};

export function DataSourceBadge({ source, tooltip, className }: Props) {
  const tip = source === "mock" ? MOCK_TOOLTIP : tooltip;
  return (
    <span
      title={tip}
      className={cn(
        "inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold tracking-wide border cursor-default",
        colorMap[source],
        className
      )}
    >
      {labelMap[source]}
    </span>
  );
}
