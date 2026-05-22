import { useEffect, useState } from "react";
import { api, type KpiTile, type FlowResponse } from "@/lib/api";
import { CitationCard } from "@/components/citation-card";
import { DataSourceBadge } from "@/components/data-source-badge";
import { CredibilityBanner } from "@/components/credibility-banner";
import type { DataSource } from "@/components/data-source-badge";

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmt(v: number | string | null | undefined, unit?: string): string {
  if (v === null || v === undefined) return "—";
  const n = typeof v === "number" ? v : parseFloat(String(v));
  if (isNaN(n)) return String(v);
  const s = Number.isInteger(n) ? String(n) : n.toFixed(1);
  return unit ? `${s} ${unit}` : s;
}

// ── Status strip ─────────────────────────────────────────────────────────────

function StatusStrip({
  adapter,
  source,
}: {
  adapter: string;
  source: DataSource | "";
}) {
  if (!adapter) return null;
  return (
    <div className="flex items-center gap-3 px-4 py-2 rounded-lg border border-border bg-card/50 text-xs text-muted-foreground flex-wrap">
      <span>
        Adapter:{" "}
        <span className="font-mono text-foreground">{adapter}</span>
      </span>
      {source && <DataSourceBadge source={source} />}
      {source === "mock" && (
        <span className="ml-auto text-yellow-400/80">
          Data is synthetic — not suitable for enforcement or accuracy claims
        </span>
      )}
    </div>
  );
}

// ── KPI tile grid ─────────────────────────────────────────────────────────────

function KpiGrid({ tiles }: { tiles: KpiTile[] }) {
  return (
    <div className="space-y-3">
      <h2 className="text-sm font-semibold text-foreground">Key Performance Indicators</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {tiles.map((tile) => (
          <CitationCard
            key={tile.key}
            title={tile.label}
            source={tile.data_source}
            tooltip={tile.tooltip}
          >
            {tile.key === "congestion" ? (
              <span className={tile.value === "CONGESTED" ? "text-yellow-400" : "text-emerald-400"}>
                {String(tile.value ?? "—")}
              </span>
            ) : (
              fmt(tile.value as number | string | null, tile.unit)
            )}
          </CitationCard>
        ))}
      </div>
    </div>
  );
}

// ── Per-class bar chart ───────────────────────────────────────────────────────

function PerClassBars({
  counts,
  source,
}: {
  counts: Record<string, number>;
  source: DataSource;
}) {
  const entries = Object.entries(counts).sort(([, a], [, b]) => b - a);
  if (entries.length === 0) return null;
  const max = Math.max(...entries.map(([, v]) => v), 1);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold text-foreground">Class Breakdown</h2>
        <DataSourceBadge source={source} />
      </div>
      <div className="rounded-lg border border-border bg-card px-4 py-4 space-y-2">
        {entries.map(([cls, count]) => (
          <div key={cls} className="flex items-center gap-3">
            <span className="text-xs font-mono text-muted-foreground w-24 truncate">{cls}</span>
            <div className="flex-1 bg-secondary/30 rounded-full h-2">
              <div
                className="bg-primary/60 h-2 rounded-full transition-all duration-300"
                style={{ width: `${(count / max) * 100}%` }}
              />
            </div>
            <span className="text-xs text-foreground w-6 text-right">{count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Congestion indicator ──────────────────────────────────────────────────────

function CongestionIndicator({ flow }: { flow: FlowResponse }) {
  if (flow.congestion_windows === 0) return null;
  return (
    <div className="flex items-center gap-2 rounded border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-xs text-yellow-400">
      ⚠ Congestion detected in {flow.congestion_windows} window
      {flow.congestion_windows !== 1 ? "s" : ""} during this period
    </div>
  );
}

// ── Benchmark cards ───────────────────────────────────────────────────────────

interface BenchmarkResult {
  adapter?: string;
  mean_latency_ms?: number;
  p95_latency_ms?: number;
  fps?: number;
  notes?: string;
  [key: string]: unknown;
}

function BenchmarkCard({
  title,
  subtitle,
  data,
  roadmapNote,
}: {
  title: string;
  subtitle: string;
  data: BenchmarkResult | null;
  roadmapNote: string;
}) {
  if (!data) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-card/50 px-4 py-6 flex flex-col items-center gap-2 text-center">
        <span className="text-xs font-semibold text-muted-foreground">{title}</span>
        <span className="text-[10px] text-muted-foreground/60">{subtitle}</span>
        <div className="mt-2 rounded border border-border/50 bg-secondary/20 px-2 py-1">
          <span className="text-[10px] text-muted-foreground/50">
            No artifact present · {roadmapNote}
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card px-4 py-4 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-foreground">{title}</span>
        <DataSourceBadge source="validated-benchmark" />
      </div>
      <span className="text-[10px] text-muted-foreground">{subtitle}</span>
      <div className="grid grid-cols-2 gap-2 mt-1">
        {data.mean_latency_ms != null && (
          <div>
            <span className="text-xl font-bold text-foreground">
              {data.mean_latency_ms.toFixed(1)}
            </span>
            <span className="text-[10px] text-muted-foreground ml-1">ms mean</span>
          </div>
        )}
        {data.p95_latency_ms != null && (
          <div>
            <span className="text-xl font-bold text-foreground">
              {data.p95_latency_ms.toFixed(1)}
            </span>
            <span className="text-[10px] text-muted-foreground ml-1">ms p95</span>
          </div>
        )}
        {data.fps != null && (
          <div>
            <span className="text-xl font-bold text-foreground">{data.fps}</span>
            <span className="text-[10px] text-muted-foreground ml-1">FPS</span>
          </div>
        )}
      </div>
      {data.notes && (
        <p className="text-[10px] text-muted-foreground/70 mt-1">{String(data.notes)}</p>
      )}
    </div>
  );
}

function BenchmarkSection({
  benchmarks,
}: {
  benchmarks: {
    jetson: BenchmarkResult | null;
    cpu_baseline: BenchmarkResult | null;
    rtx_dev: BenchmarkResult | null;
  } | null;
}) {
  return (
    <div className="space-y-3">
      <h2 className="text-sm font-semibold text-foreground">Hardware Benchmarks</h2>
      <p className="text-xs text-muted-foreground">
        Benchmark tiles are populated only from validated artifact files. Empty
        state indicates the benchmark has not yet been run at this phase.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <BenchmarkCard
          title="Jetson Thor AGX"
          subtitle="Production target — TensorRT FP16"
          data={benchmarks?.jetson ?? null}
          roadmapNote="Roadmap Phase 3"
        />
        <BenchmarkCard
          title="CPU Baseline"
          subtitle="Development — ONNX Runtime CPU"
          data={benchmarks?.cpu_baseline ?? null}
          roadmapNote="Roadmap Phase 2"
        />
        <BenchmarkCard
          title="RTX 5090 Dev"
          subtitle="Development — ONNX Runtime CUDA"
          data={benchmarks?.rtx_dev ?? null}
          roadmapNote="Roadmap Phase 2"
        />
      </div>
    </div>
  );
}

// ── Flow panel ────────────────────────────────────────────────────────────────

function FlowPanel({ flow }: { flow: FlowResponse }) {
  const source = flow.data_source as DataSource;
  return (
    <div className="space-y-3">
      <h2 className="text-sm font-semibold text-foreground">Traffic Flow</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <CitationCard title="Vehicles in frame" source={source} tooltip={flow.tooltip}>
          {fmt(flow.vehicle_count)}
        </CitationCard>
        <CitationCard title="Persons in frame" source={source} tooltip={flow.tooltip}>
          {fmt(flow.person_count)}
        </CitationCard>
        <CitationCard title="Congestion windows" source={source} tooltip={flow.tooltip}>
          {fmt(flow.congestion_windows)}
        </CitationCard>
        <CitationCard title="Window start" source={source} tooltip={flow.tooltip}>
          <span className="text-base">
            {flow.window_start ? new Date(flow.window_start).toLocaleTimeString() : "—"}
          </span>
        </CitationCard>
      </div>
      <CongestionIndicator flow={flow} />
      <PerClassBars counts={flow.class_counts ?? {}} source={source} />
    </div>
  );
}

// ── Root page ─────────────────────────────────────────────────────────────────

export function MetricsPage() {
  const [tiles, setTiles] = useState<KpiTile[]>([]);
  const [adapter, setAdapter] = useState<string>("");
  const [topSource, setTopSource] = useState<DataSource | "">("");
  const [flow, setFlow] = useState<FlowResponse | null>(null);
  const [benchmarks, setBenchmarks] = useState<{
    jetson: BenchmarkResult | null;
    cpu_baseline: BenchmarkResult | null;
    rtx_dev: BenchmarkResult | null;
  } | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    try {
      const [kpisRes, flowRes, bmRes] = await Promise.allSettled([
        api.metrics.kpis(),
        api.metrics.flow(),
        fetch("/metrics/benchmarks").then((r) => r.json()),
      ]);
      if (kpisRes.status === "fulfilled") {
        setTiles(kpisRes.value.tiles ?? []);
        setAdapter(kpisRes.value.adapter ?? "");
        setTopSource((kpisRes.value as unknown as Record<string, unknown>).data_source as DataSource ?? "");
      }
      if (flowRes.status === "fulfilled") setFlow(flowRes.value);
      if (bmRes.status === "fulfilled") setBenchmarks(bmRes.value as typeof benchmarks);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, []);

  const isMock = adapter === "mock";

  return (
    <div className="p-4 space-y-6">
      {isMock && <CredibilityBanner />}
      <StatusStrip adapter={adapter} source={topSource} />

      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Metrics &amp; KPIs</h1>
      </div>

      {loading && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-20 rounded-lg snapshot-shimmer" />
          ))}
        </div>
      )}

      {!loading && (
        <>
          {tiles.length > 0 && <KpiGrid tiles={tiles} />}
          {flow && <FlowPanel flow={flow} />}
          <BenchmarkSection benchmarks={benchmarks} />
          {tiles.length === 0 && !flow && (
            <div className="py-12 text-center text-sm text-muted-foreground">
              No metrics available yet. Start the detection pipeline to populate data.
            </div>
          )}
        </>
      )}
    </div>
  );
}
