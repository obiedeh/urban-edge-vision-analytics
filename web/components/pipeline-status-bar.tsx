import { useEffect, useRef, useState } from "react";
import { api, type PipelineStatus, type OllamaModel } from "@/lib/api";
import {
  Activity, Square, Play, ChevronDown, ChevronRight,
  AlertTriangle, Loader2, CheckCircle2, XCircle, Wifi,
  MoreHorizontal,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Adapter definitions ───────────────────────────────────────────────────────

const LOCAL_BACKENDS = [
  { value: "vllm",   label: "vLLM",   hint: "vLLM server · any HuggingFace model" },
  { value: "ollama", label: "Ollama", hint: "Ollama · quantised GGUF models" },
  { value: "mock",   label: "Mock",   hint: "Synthetic detections · no model needed" },
] as const;

// Preset endpoint ports — user picks one, models auto-load
interface EndpointPreset {
  url: string;       // full base URL passed to the probe
  label: string;     // shown in dropdown
}
function getEndpointPresets(backend: string): EndpointPreset[] {
  if (backend === "vllm")   return [
    { url: "http://localhost:8001", label: ":8001 (vLLM default)" },
    { url: "http://localhost:8000", label: ":8000" },
    { url: "custom", label: "Custom URL…" },
  ];
  if (backend === "ollama") return [
    { url: "http://localhost:11434", label: ":11434 (Ollama default)" },
    { url: "custom", label: "Custom URL…" },
  ];
  return [];
}

const CLOUD_BACKENDS = [
  { value: "nvidia-cosmos", label: "Cosmos (cloud)" },
  { value: "nvidia-nim",    label: "NIM (cloud)" },
  { value: "nvidia-vss",    label: "VSS (cloud)" },
] as const;

const LOCAL_ADAPTERS  = new Set(["mock", "ollama", "vllm"]);
const NVIDIA_ADAPTERS = new Set(["nvidia-nim", "nvidia-vss", "nvidia-cosmos"]);

type ProbeState = "idle" | "probing" | "online" | "offline";

interface Props { pollMs?: number }

export function PipelineStatusBar({ pollMs = 3000 }: Props) {
  const [status, setStatus]         = useState<PipelineStatus | null>(null);
  const [busy, setBusy]             = useState(false);
  const [logOpen, setLogOpen]       = useState(false);
  const [switchOpen, setSwitchOpen] = useState(false);
  const [showCloud, setShowCloud]   = useState(false);

  // Switcher fields
  const [backend, setBackend]               = useState("vllm");
  const [selectedEndpoint, setSelectedEndpoint] = useState("http://localhost:8001");
  const [customUrl, setCustomUrl]           = useState("");   // only used when preset = "custom"
  const [selectedModel, setSelectedModel]   = useState("");
  const [customModel, setCustomModel]       = useState("");
  const [nvidiaKey, setNvidiaKey]           = useState("");
  const [probe, setProbe]                   = useState<ProbeState>("idle");
  // Models detected from the active endpoint
  const [installedModels, setInstalledModels] = useState<OllamaModel[]>([]);

  const probeRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Poll status ─────────────────────────────────────────────────────────────
  useEffect(() => {
    let dead = false;
    const tick = async () => {
      try { const s = await api.pipeline.status(); if (!dead) setStatus(s); }
      catch { /* silent */ }
    };
    tick();
    const t = setInterval(tick, pollMs);
    return () => { dead = true; clearInterval(t); };
  }, [pollMs]);

  // ── On open: pre-populate from running config, then auto-probe ──────────────
  useEffect(() => {
    if (!switchOpen) return;
    const activeAdapter = status?.adapter ?? "vllm";
    setBackend(activeAdapter);
    const presets = getEndpointPresets(activeAdapter);
    const firstUrl = presets[0]?.url ?? "";
    setSelectedEndpoint(firstUrl);
    setProbe("idle");
    setInstalledModels([]);
    setSelectedModel("");
    setCustomModel("");
    // Auto-probe first preset to populate model list immediately
    if (firstUrl && firstUrl !== "custom" && activeAdapter !== "mock") {
      changeEndpoint(firstUrl);
    } else if (activeAdapter === "mock") {
      setProbe("online");
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [switchOpen]);

  // Auto-select first vision model
  useEffect(() => {
    if (installedModels.length > 0 && !selectedModel && !customModel) {
      const first = installedModels.find(m => m.vision) ?? installedModels[0];
      setSelectedModel(first.name);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [installedModels]);

  function changeBackend(v: string) {
    setBackend(v);
    setProbe("idle");
    setSelectedModel("");
    setCustomModel("");
    setCustomUrl("");
    setInstalledModels([]);
    // Seed the first preset for this backend
    const presets = getEndpointPresets(v);
    setSelectedEndpoint(presets[0]?.url ?? "");
    if (probeRef.current) clearTimeout(probeRef.current);
    if (v === "mock") { setProbe("online"); }
  }

  async function changeEndpoint(url: string) {
    setSelectedEndpoint(url);
    setSelectedModel("");
    setCustomModel("");
    setInstalledModels([]);
    if (url === "custom") { setProbe("idle"); return; }
    // Auto-probe the chosen port
    setProbe("probing");
    try {
      if (backend === "vllm") {
        const r = await api.localInference.vllm.status(url);
        setProbe(r.running ? "online" : "offline");
        if (r.running) {
          const mr = await api.localInference.vllm.models(url);
          setInstalledModels(mr.models);
        }
      } else if (backend === "ollama") {
        const r = await api.localInference.ollama.status(url);
        setProbe(r.running ? "online" : "offline");
        if (r.running) {
          const mr = await api.localInference.ollama.models(url);
          setInstalledModels(mr.models);
        }
      }
    } catch { setProbe("offline"); }
  }

  const effectiveModel = customModel.trim() || selectedModel;
  const isNvidia   = NVIDIA_ADAPTERS.has(backend);
  const resolvedUrl = isNvidia
    ? customUrl.trim()
    : selectedEndpoint === "custom" ? customUrl.trim() : selectedEndpoint;
  const needsProbe = backend !== "mock" && backend !== "disabled";
  const canApply   = !needsProbe || probe === "online";

  // ── Probe ────────────────────────────────────────────────────────────────────
  async function runProbe() {
    setProbe("probing");
    const ep = resolvedUrl || undefined;
    try {
      if (backend === "ollama") {
        const r = await api.localInference.ollama.status(ep);
        setProbe(r.running ? "online" : "offline");
        if (r.running) {
          const mr = await api.localInference.ollama.models(ep);
          setInstalledModels(mr.models);
        }
      } else if (backend === "vllm") {
        const r = await api.localInference.vllm.status(ep);
        setProbe(r.running ? "online" : "offline");
        if (r.running) {
          const mr = await api.localInference.vllm.models(ep);
          setInstalledModels(mr.models);
        }
      } else if (backend === "mock") {
        setProbe("online");
      } else if (isNvidia) {
        if (!resolvedUrl) { setProbe("offline"); return; }
        const r = await fetch(resolvedUrl, {
          method: "HEAD", signal: AbortSignal.timeout(5000),
        }).catch(() => null);
        setProbe(r ? "online" : "offline");
      }
    } catch { setProbe("offline"); }
  }

  // ── Stop ─────────────────────────────────────────────────────────────────────
  async function stop() {
    setBusy(true);
    try {
      await api.pipeline.stop();
      await api.pipeline.switchAdapter("disabled").catch(() => null);
      setStatus(s => s ? { ...s, state: "stopped" } : s);
      setSwitchOpen(false);
    } catch { /* ignore */ } finally { setBusy(false); }
  }

  // ── Apply ─────────────────────────────────────────────────────────────────────
  async function applyAdapter() {
    setBusy(true);
    try {
      if (LOCAL_ADAPTERS.has(backend)) {
        await api.pipeline.switchAdapter(
          backend, undefined, undefined,
          (backend === "ollama" || backend === "vllm") ? effectiveModel || undefined : undefined,
          resolvedUrl || undefined,
        );
      } else {
        await api.pipeline.switchAdapter(backend, resolvedUrl || undefined, nvidiaKey || undefined);
      }
      setSwitchOpen(false);
      setProbe("idle");
      setStatus(s => s ? { ...s, state: "running", adapter: backend } : s);
    } catch { /* ignore */ } finally { setBusy(false); }
  }

  // ── Derived display ───────────────────────────────────────────────────────────
  const isStopped = !status || status.state === "stopped";
  const isRunning = status?.state === "running";
  const isFailed  = status?.state === "failed";

  const dotCls = isRunning ? "bg-emerald-400 animate-pulse"
    : isFailed ? "bg-red-400" : "bg-muted-foreground/30";

  const uptime = status?.uptime_seconds != null
    ? status.uptime_seconds < 60
      ? `${Math.round(status.uptime_seconds)}s`
      : `${Math.round(status.uptime_seconds / 60)}m`
    : null;

  // ── Sub-components ────────────────────────────────────────────────────────────

  const ProbeBadge = () => {
    if (probe === "idle") return null;
    if (probe === "probing") return (
      <span className="flex items-center gap-1 text-[10px] text-yellow-400">
        <Loader2 className="h-3 w-3 animate-spin" /> Checking…
      </span>
    );
    if (probe === "online") return (
      <span className="flex items-center gap-1 text-[10px] text-emerald-400 font-semibold">
        <CheckCircle2 className="h-3 w-3" /> Online
      </span>
    );
    return (
      <span className="flex items-center gap-1 text-[10px] text-red-400">
        <XCircle className="h-3 w-3" /> Unreachable
      </span>
    );
  };

  // ── Switch panel ──────────────────────────────────────────────────────────────
  const switcherPanel = switchOpen && (
    <div className="border-t border-border px-4 pt-3 pb-4 space-y-3">

      {/* ① Backend tabs */}
      <div>
        <p className="text-[10px] text-muted-foreground/60 uppercase tracking-wider font-medium mb-1.5">
          Inference backend
        </p>
        <div className="flex items-center gap-1 flex-wrap">
          {LOCAL_BACKENDS.map(b => (
            <button
              key={b.value}
              type="button"
              title={b.hint}
              onClick={() => changeBackend(b.value)}
              className={cn(
                "px-3 py-1 rounded text-xs font-medium border transition-colors",
                backend === b.value
                  ? "bg-primary/15 border-primary/50 text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground hover:border-border/80"
              )}
            >
              {b.label}
            </button>
          ))}
          {/* Cloud expander */}
          <button
            type="button"
            onClick={() => setShowCloud(v => !v)}
            className={cn(
              "flex items-center gap-0.5 px-2 py-1 rounded text-xs border transition-colors",
              NVIDIA_ADAPTERS.has(backend)
                ? "bg-primary/15 border-primary/50 text-foreground"
                : "border-border text-muted-foreground hover:text-foreground"
            )}
          >
            <MoreHorizontal className="h-3.5 w-3.5" />
            Cloud
          </button>
          {showCloud && CLOUD_BACKENDS.map(b => (
            <button
              key={b.value}
              type="button"
              onClick={() => { changeBackend(b.value); setShowCloud(false); }}
              className={cn(
                "px-3 py-1 rounded text-xs font-medium border transition-colors",
                backend === b.value
                  ? "bg-primary/15 border-primary/50 text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground"
              )}
            >
              {b.label}
            </button>
          ))}
        </div>
      </div>

      {/* ② Endpoint — preset dropdown for local, text for cloud */}
      {backend !== "mock" && (
        <div className="space-y-1.5">
          <p className="text-[10px] text-muted-foreground/60 uppercase tracking-wider font-medium">
            Endpoint
          </p>

          {/* Local backends: preset port dropdown */}
          {!isNvidia && (
            <>
              <div className="flex items-center gap-1.5">
                <select
                  value={selectedEndpoint}
                  onChange={e => changeEndpoint(e.target.value)}
                  className="flex-1 rounded border border-input bg-background px-2 py-1.5 text-xs text-foreground"
                >
                  {getEndpointPresets(backend).map(p => (
                    <option key={p.url} value={p.url}>{p.label}</option>
                  ))}
                </select>
                {/* Status badge inline */}
                {probe === "probing" && (
                  <span className="flex items-center gap-1 text-[10px] text-yellow-400 shrink-0">
                    <Loader2 className="h-3 w-3 animate-spin" /> Detecting…
                  </span>
                )}
                {probe === "online" && (
                  <span className="flex items-center gap-1 text-[10px] text-emerald-400 font-semibold shrink-0">
                    <CheckCircle2 className="h-3 w-3" /> Online
                  </span>
                )}
                {probe === "offline" && (
                  <span className="flex items-center gap-1 text-[10px] text-red-400 shrink-0">
                    <XCircle className="h-3 w-3" /> Offline
                  </span>
                )}
              </div>
              {/* Custom URL input */}
              {selectedEndpoint === "custom" && (
                <div className="flex gap-1.5">
                  <input
                    type="url"
                    placeholder="http://jetson-thor:8001"
                    value={customUrl}
                    onChange={e => { setCustomUrl(e.target.value); setProbe("idle"); }}
                    className="flex-1 min-w-0 rounded border border-input bg-background px-2 py-1.5 text-[10px] font-mono text-foreground placeholder:text-muted-foreground/35"
                  />
                  <button
                    type="button"
                    onClick={runProbe}
                    disabled={probe === "probing" || !customUrl.trim()}
                    className="shrink-0 flex items-center gap-1 rounded border border-border px-2.5 py-1 text-[10px] text-muted-foreground hover:text-foreground hover:border-primary/40 disabled:opacity-40 transition-colors"
                  >
                    <Wifi className="h-3 w-3" /> Check
                  </button>
                </div>
              )}
              <p className="text-[10px] text-muted-foreground/35">
                No API key required · select a port to auto-detect running models
              </p>
            </>
          )}

          {/* NVIDIA cloud: manual URL + optional key */}
          {isNvidia && (
            <div className="space-y-1.5">
              <div className="flex gap-1.5">
                <input
                  type="url"
                  placeholder="http://your-nim-server/v1"
                  value={customUrl}
                  onChange={e => { setCustomUrl(e.target.value); setProbe("idle"); }}
                  className="flex-1 min-w-0 rounded border border-input bg-background px-2 py-1.5 text-[10px] font-mono text-foreground placeholder:text-muted-foreground/35"
                />
                <button
                  type="button"
                  onClick={runProbe}
                  disabled={probe === "probing" || !customUrl.trim()}
                  className="shrink-0 flex items-center gap-1 rounded border border-border px-2.5 py-1 text-[10px] text-muted-foreground hover:text-foreground hover:border-primary/40 disabled:opacity-40 transition-colors"
                >
                  {probe === "probing" ? <Loader2 className="h-3 w-3 animate-spin" /> : <Wifi className="h-3 w-3" />}
                  Check
                </button>
              </div>
              <ProbeBadge />
              <input
                type="password"
                placeholder="API key (optional — leave blank for local NIM)"
                value={nvidiaKey}
                onChange={e => setNvidiaKey(e.target.value)}
                className="w-full rounded border border-input bg-background px-2 py-1.5 text-[10px] text-foreground placeholder:text-muted-foreground/35"
              />
            </div>
          )}
        </div>
      )}

      {/* ③ Model — vLLM / Ollama only */}
      {(backend === "ollama" || backend === "vllm") && (
        <div className="space-y-1.5">
          <p className="text-[10px] text-muted-foreground/60 uppercase tracking-wider font-medium">
            Model
          </p>

          {/* Detected models from the active endpoint */}
          {installedModels.length > 0 ? (
            <select
              value={selectedModel}
              onChange={e => { setSelectedModel(e.target.value); setCustomModel(""); }}
              className="w-full rounded border border-input bg-background px-2 py-1.5 text-xs text-foreground"
            >
              {installedModels.map(m => (
                <option key={m.name} value={m.name}>
                  {m.vision ? "👁  " : "📝  "}{m.name}
                  {m.size_gb ? `  ·  ${m.size_gb} GB` : ""}
                  {!m.vision ? "  (text only)" : ""}
                </option>
              ))}
            </select>
          ) : probe === "online" ? (
            <p className="text-[10px] text-muted-foreground/50 italic">
              No models found at this endpoint.
            </p>
          ) : probe === "probing" ? (
            <p className="text-[10px] text-muted-foreground/50 flex items-center gap-1">
              <Loader2 className="h-3 w-3 animate-spin" /> Detecting models…
            </p>
          ) : (
            <p className="text-[10px] text-muted-foreground/50">
              Select an endpoint above to detect running models.
            </p>
          )}

          {/* Free-text override — type any model name not in the list */}
          <input
            type="text"
            placeholder={
              backend === "vllm"
                ? "or type a model ID: nvidia/cosmos-reason2-2b …"
                : "or type: gemma4:27b-q4_K_M, cosmos-reason2:2b …"
            }
            value={customModel}
            onChange={e => { setCustomModel(e.target.value); if (e.target.value) setSelectedModel(""); }}
            className="w-full rounded border border-input bg-background px-2 py-1.5 text-[10px] font-mono text-foreground placeholder:text-muted-foreground/30"
          />

          {/* Active selection preview */}
          {effectiveModel && (
            <p className="text-[10px] text-emerald-400 flex items-center gap-1.5">
              <CheckCircle2 className="h-3 w-3 shrink-0" />
              <span className="font-mono">{effectiveModel}</span>
              {installedModels.find(m => m.name === effectiveModel && !m.vision) && (
                <span className="text-yellow-400 flex items-center gap-0.5">
                  <AlertTriangle className="h-3 w-3" /> text-only
                </span>
              )}
            </p>
          )}
        </div>
      )}

      {/* ④ Actions */}
      <div className="flex items-center justify-between pt-1 border-t border-border">
        <button
          onClick={stop}
          disabled={busy || isStopped}
          className="text-[10px] text-red-400/60 hover:text-red-400 transition-colors disabled:opacity-30"
        >
          Stop pipeline
        </button>
        <button
          onClick={applyAdapter}
          disabled={busy || !canApply}
          title={!canApply ? "Check connection first" : undefined}
          className={cn(
            "flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors",
            canApply
              ? "bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              : "bg-secondary text-muted-foreground cursor-not-allowed opacity-40 border border-border"
          )}
        >
          {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
          {busy ? "Starting…" : canApply ? "Apply" : "Check first"}
        </button>
      </div>
    </div>
  );

  // ── Status bar ────────────────────────────────────────────────────────────────
  const adapterLabel = status?.adapter
    ? LOCAL_BACKENDS.find(b => b.value === status.adapter)?.label ?? status.adapter
    : null;

  const statusLine = (
    <div className="flex items-center gap-2.5 px-4 py-2 text-xs flex-wrap">
      <span className={cn("h-2 w-2 rounded-full shrink-0", dotCls)} />

      {isRunning && (
        <span className="text-emerald-400 font-medium flex items-center gap-1">
          <Activity className="h-3 w-3" /> Running
        </span>
      )}
      {isFailed && (
        <span className="text-red-400 font-medium flex items-center gap-1">
          <AlertTriangle className="h-3 w-3" /> Failed (exit {status?.exit_code})
        </span>
      )}
      {isStopped && (
        <span className="text-muted-foreground">Stopped</span>
      )}

      {/* Adapter + model pill */}
      {adapterLabel && (
        <span className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-secondary/60 border border-border text-[10px] text-foreground/70 font-mono">
          {adapterLabel}
        </span>
      )}
      {status?.camera_id && (
        <span className="text-muted-foreground/60 text-[10px]">{status.camera_id}</span>
      )}
      {status?.synthetic && (
        <span className="px-1.5 py-0.5 rounded border border-yellow-500/30 bg-yellow-500/10 text-yellow-400 text-[10px]">
          SYNTHETIC
        </span>
      )}
      {uptime && <span className="text-muted-foreground/50 text-[10px]">up {uptime}</span>}

      {/* Right side controls */}
      <div className="ml-auto flex items-center gap-2">
        {(status?.log_tail?.length ?? 0) > 0 && (
          <button
            onClick={() => setLogOpen(v => !v)}
            className="flex items-center gap-0.5 text-muted-foreground/50 hover:text-muted-foreground text-[10px] transition-colors"
          >
            {logOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            log
          </button>
        )}
        <button
          onClick={() => setSwitchOpen(v => !v)}
          className={cn(
            "flex items-center gap-0.5 text-[10px] transition-colors border rounded px-2 py-0.5",
            switchOpen
              ? "text-foreground border-primary/40"
              : "text-muted-foreground hover:text-foreground border-border hover:border-border/80"
          )}
        >
          {switchOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          Switch
        </button>
        {(isRunning || isFailed) && (
          <button
            onClick={stop}
            disabled={busy}
            className="flex items-center gap-1 rounded border border-red-500/25 bg-red-500/8 px-2 py-0.5 text-[10px] text-red-400/70 hover:text-red-400 hover:bg-red-500/15 disabled:opacity-40 transition-colors"
          >
            {busy ? <Loader2 className="h-2.5 w-2.5 animate-spin" /> : <Square className="h-2.5 w-2.5" />}
            {busy ? "…" : "Stop"}
          </button>
        )}
        {isStopped && (
          <button
            onClick={() => setSwitchOpen(v => !v)}
            className="flex items-center gap-1 rounded border border-primary/30 bg-primary/8 px-2 py-0.5 text-[10px] text-primary/80 hover:text-primary hover:bg-primary/15 transition-colors"
          >
            <Play className="h-2.5 w-2.5" /> Start
          </button>
        )}
      </div>
    </div>
  );

  return (
    <div className="border-b border-border bg-secondary/10">
      {statusLine}
      {switcherPanel}
      {logOpen && (status?.log_tail?.length ?? 0) > 0 && (
        <div className="px-4 pb-2">
          <pre className="rounded bg-black/40 border border-border px-3 py-2 text-[10px] font-mono text-foreground/60 overflow-x-auto whitespace-pre-wrap max-h-28 overflow-y-auto">
            {status?.log_tail.join("\n")}
          </pre>
        </div>
      )}
    </div>
  );
}
