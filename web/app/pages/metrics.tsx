import { useEffect, useState } from "react";
import { api, type KpiTile, type FlowResponse } from "@/lib/api";
import { CitationCard } from "@/components/citation-card";
import { CredibilityBanner } from "@/components/credibility-banner";
import type { DataSource } from "@/components/data-source-badge";

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmt(v: number | string | null, unit?: string): string {
  if (v === null || v === undefined) return "—";
  const n = typeof v === "number" ? v : parseFloat(String(v));
  if (isNaN(n)) return String(v);
  const s = Number.isInteger(n) ? String(n) : n.toFixed(1);
  return unit ? `${s} ${unit}` : s;
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
        <CitationCard title="Window" source={source} tooltip={flow.tooltip}>
          <span className="text-base">
            {flow.window_start
              ? new Date(flow.window_start).toLocaleTimeString()
              : "—"}
          </span>
        </CitationCard>
      </div>

      {Object.keys(flow.class_counts ?? {}).length > 0 && (
        <div className="rounded-lg border border-border bg-card px-4 py-3">
          <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">
            Class breakdown
          </p>
          <div className="flex flex-wrap gap-3">
            {Object.entries(flow.class_counts).map(([cls, count]) => (
              <div key={cls} className="flex flex-col items-center">
                <span className="text-lg font-bold text-foreground">{count}</span>
                <span className="text-[10px] text-muted-foreground uppercase tracking-wide">
                  {cls}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {flow.congestion_windows > 0 && (
        <div className="flex items-center gap-2 rounded border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-xs text-yellow-400">
          ⚠ Congestion detected in {flow.congestion_windows} window
          {flow.congestion_windows !== 1 ? "s" : ""}
        </div>
      )}
    </div>
  );
}

// ── KPI tiles ─────────────────────────────────────────────────────────────────

function KpiGrid({ tiles }: { tiles: KpiTile[] }) {
  return (
    <div className="space-y-3">
      <h2 className="text-sm font-semibold text-foreground">Key Performance Indicators</h2>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
        {tiles.map((tile) => (
          <CitationCard
            key={tile.key}
            title={tile.label}
            source={tile.data_source}
            tooltip={tile.tooltip}
          >
            {fmt(tile.value, tile.unit)}
          </CitationCard>
        ))}
      </div>
    </div>
  );
}

// ── Inference panel ───────────────────────────────────────────────────────────

function InferencePanel({ data }: { data: Record<string, unknown> }) {
  const latency = data.inference_latency_ms as Record<string, unknown> | undefined;
  if (!latency) return null;

  const mean = latency.mean as number | null;
  const p50 = latency.p50 as number | null;
  const p95 = latency.p95 as number | null;
  const p99 = latency.p99 as number | null;
  const count = latency.sample_count as number | null;

  return (
    <div className="space-y-3">
      <h2 className="text-sm font-semibold text-foreground">Inference Latency</h2>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {[
          { label: "Mean", value: mean },
          { label: "p50", value: p50 },
          { label: "p95", value: p95 },
          { label: "p99", value: p99 },
          { label: "Samples", value: count },
        ].map(({ label, value }) => (
          <div
            key={label}
            className="rounded-lg border border-border bg-card px-4 py-3 flex flex-col gap-1"
          >
            <span className="text-xs text-muted-foreground uppercase tracking-wide">
              {label}
            </span>
            <span className="text-2xl font-bold text-foreground">
              {value != null ? (label === "Samples" ? String(value) : `${Number(value).toFixed(1)}`) : "—"}
            </span>
            {label !== "Samples" && (
              <span className="text-[10px] text-muted-foreground">ms</span>
            )}
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        Latency includes preprocessing, model forward pass, and NMS. Does not include camera
        I/O or network transit.
      </p>
    </div>
  );
}

// ── Root page ─────────────────────────────────────────────────────────────────

export function MetricsPage() {
  const [tiles, setTiles] = useState<KpiTile[]>([]);
  const [adapter, setAdapter] = useState<string>("");
  const [flow, setFlow] = useState<FlowResponse | null>(null);
  const [inference, setInference] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    try {
      const [kpisRes, flowRes, inferRes] = await Promise.allSettled([
        api.metrics.kpis(),
        api.metrics.flow(),
        api.metrics.inference(),
      ]);
      if (kpisRes.status === "fulfilled") {
        setTiles(kpisRes.value.tiles ?? []);
        setAdapter(kpisRes.value.adapter ?? "");
      }
      if (flowRes.status === "fulfilled") setFlow(flowRes.value);
      if (inferRes.status === "fulfilled") setInference(inferRes.value);
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

      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Metrics &amp; KPIs</h1>
        <span className="text-xs text-muted-foreground">
          {isMock ? "Mock adapter — data is simulated" : `Adapter: ${adapter}`}
        </span>
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
          {inference && <InferencePanel data={inference} />}
          {tiles.length === 0 && !flow && !inference && (
            <div className="py-12 text-center text-sm text-muted-foreground">
              No metrics available yet. Start the detection pipeline to populate data.
            </div>
          )}
        </>
      )}
    </div>
  );
}
