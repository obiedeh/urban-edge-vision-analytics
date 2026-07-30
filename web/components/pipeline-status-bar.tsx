import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  api,
  type PipelineStatus,
  type OllamaModel,
  type CatalogModel,
  type VllmStatus,
} from "@/lib/api";
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
    { url: "http://localhost:8000", label: ":8000 (vLLM default)" },
    { url: "http://localhost:8001", label: ":8001" },
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
  const [selectedEndpoint, setSelectedEndpoint] = useState("http://localhost:8000");
  const [customUrl, setCustomUrl]           = useState("");   // only used when preset = "custom"
  const [selectedModel, setSelectedModel]   = useState("");
  const [customModel, setCustomModel]       = useState("");
  const [nvidiaKey, setNvidiaKey]           = useState("");
  const [probe, setProbe]                   = useState<ProbeState>("idle");
  // Models detected from the active endpoint
  const [installedModels, setInstalledModels] = useState<OllamaModel[]>([]);
  const [catalogModels, setCatalogModels] = useState<CatalogModel[]>([]);
  const [vllmStatus, setVllmStatus] = useState<VllmStatus | null>(null);
  const [vllmBusy, setVllmBusy] = useState(false);
  const [actionError, setActionError] = useState("");

  const probeRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const selectedVllmEndpoint =
    selectedEndpoint === "custom" ? customUrl.trim() : selectedEndpoint;
  const vllmPollEndpoint =
    backend === "vllm" && selectedVllmEndpoint
      ? selectedVllmEndpoint
      : "http://localhost:8000";

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

  useEffect(() => {
    let dead = false;
    const tick = async () => {
      try {
        const s = await api.localInference.vllm.status(vllmPollEndpoint);
        if (!dead) setVllmStatus(s);
      } catch {
        if (!dead) setVllmStatus(null);
      }
    };
    tick();
    const t = setInterval(tick, pollMs);
    return () => { dead = true; clearInterval(t); };
  }, [pollMs, vllmPollEndpoint]);

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

  useEffect(() => {
    if (!switchOpen) return;
    let dead = false;
    api.localInference.catalog()
      .then(r => { if (!dead) setCatalogModels(r.models); })
      .catch(() => { if (!dead) setCatalogModels([]); });
    return () => { dead = true; };
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
    setActionError("");
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
    setActionError("");
    setSelectedModel("");
    setCustomModel("");
    setInstalledModels([]);
    if (url === "custom") { setProbe("idle"); return; }
    // Auto-probe the chosen port
    setProbe("probing");
    try {
      if (backend === "vllm") {
        const r = await api.localInference.vllm.status(url);
        setVllmStatus(r);
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

  const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

  function actionErrorMessage(err: unknown, fallback: string): string {
    if (err instanceof ApiError) {
      const detail = err.detail?.detail ?? err.detail;
      if (typeof detail === "string") return detail;
      if (detail && typeof detail === "object" && "message" in detail) {
        const message = (detail as { message?: unknown }).message;
        if (typeof message === "string") return message;
      }
      return fallback;
    }
    return err instanceof Error ? err.message : fallback;
  }

  async function refreshVllm(endpoint?: string): Promise<VllmStatus | null> {
    const status = await api.localInference.vllm.status(endpoint);
    setVllmStatus(status);
    setProbe(status.running ? "online" : "offline");
    if (status.running) {
      const models = await api.localInference.vllm.models(endpoint);
      setInstalledModels(models.models);
    }
    return status;
  }

  function vllmFailureMessage(status: VllmStatus | null): string {
    const logText = (status?.managed_log_tail ?? []).join("\n").toLowerCase();
    const model = status?.managed_model || effectiveVllmModel || effectiveModel || "selected model";
    if (
      logText.includes("gated repo")
      || logText.includes("must have access")
      || logText.includes("401 client error")
    ) {
      return (
        `Access denied for ${model}. This Hugging Face repo is gated; accept access on `
        + "Hugging Face/NVIDIA and use a token with that access, or choose Cosmos 3 Nano."
      );
    }
    if (
      logText.includes("out of memory")
      || logText.includes("cuda error: out of memory")
      || logText.includes("not enough memory")
      || logText.includes("exit code: -9")
      || logText.includes("engine core initialization failed")
      || logText.includes("orchestrator initialization failed")
      || logText.includes("scheduler is dead")
      || logText.includes("eoferror")
    ) {
      return (
        `vLLM-Omni could not initialize ${model}. The diffusion worker was killed during startup; `
        + "free system RAM/GPU memory, confirm a real HF_TOKEN is set, unload vLLM, then retry."
      );
    }
    return `vLLM failed while loading ${model}. Check the vLLM log tail below.`;
  }

  async function waitForVllmReady(endpoint?: string): Promise<void> {
    const deadline = Date.now() + 10 * 60 * 1000;
    while (Date.now() < deadline) {
      const status = await refreshVllm(endpoint);
      if (status?.running) return;
      if (status?.managed_state === "failed") {
        throw new Error(vllmFailureMessage(status));
      }
      await sleep(3000);
    }
    throw new Error("Timed out waiting for vLLM to become ready");
  }

  async function loadVllmOnly() {
    if (!effectiveModel) {
      setActionError("Select a vLLM model first");
      return;
    }
    setVllmBusy(true);
    setActionError("");
    try {
      await api.localInference.vllm.start(effectiveVllmModel, resolvedUrl || undefined);
      await waitForVllmReady(resolvedUrl || undefined);
    } catch (err) {
      setActionError(actionErrorMessage(err, "Failed to load vLLM"));
    } finally {
      setVllmBusy(false);
    }
  }

  async function unloadVllm() {
    setVllmBusy(true);
    setActionError("");
    try {
      await api.localInference.vllm.stop();
      await refreshVllm("http://localhost:8000").catch(() => null);
    } catch (err) {
      setActionError(actionErrorMessage(err, "Failed to unload vLLM"));
    } finally {
      setVllmBusy(false);
    }
  }

  const effectiveModel = customModel.trim() || selectedModel;
  const recommendedModels = catalogModels
    .filter(m =>
      m.backend === backend
      && (m.family === "cosmos-reason2" || m.family === "cosmos3" || m.family === "gemma4")
    )
    .sort((a, b) => {
      const aGated = a.gated ? 1 : 0;
      const bGated = b.gated ? 1 : 0;
      const aRecommended = a.tags.includes("recommended") ? 0 : 1;
      const bRecommended = b.tags.includes("recommended") ? 0 : 1;
      return (
        aGated - bGated
        || aRecommended - bRecommended
        || a.vram_gb - b.vram_gb
        || a.label.localeCompare(b.label)
      );
    });
  const selectedCatalogModel = recommendedModels.find(
    m => m.name === effectiveModel || m.hf_id === effectiveModel
  );
  const effectiveVllmModel =
    backend === "vllm" && selectedCatalogModel?.hf_id
      ? selectedCatalogModel.hf_id
      : effectiveModel;
  const effectiveAdapterModel = backend === "vllm" ? effectiveVllmModel : effectiveModel;
  const isNvidia   = NVIDIA_ADAPTERS.has(backend);
  const resolvedUrl = isNvidia
    ? customUrl.trim()
    : selectedEndpoint === "custom" ? customUrl.trim() : selectedEndpoint;
  const needsProbe = backend !== "mock" && backend !== "disabled";
  const canApply = backend === "vllm"
    ? Boolean(effectiveModel && resolvedUrl)
    : !needsProbe || probe === "online";
  const vllmIsReady = Boolean(vllmStatus?.running);
  const vllmIsLoading = vllmStatus?.managed_state === "starting" && !vllmStatus.running;
  const vllmIsFailed = vllmStatus?.managed_state === "failed";
  const vllmColor = vllmIsReady
    ? "emerald"
    : vllmIsLoading
      ? "yellow"
      : "red";
  const vllmLabel = vllmIsReady
    ? "vLLM ready"
    : vllmIsLoading
      ? "vLLM loading"
      : vllmIsFailed
        ? "vLLM failed"
        : "vLLM offline";
  const vllmProgress = vllmIsReady ? 100 : vllmIsLoading ? 62 : vllmIsFailed ? 100 : 8;
  const vllmDotCls = vllmColor === "emerald"
    ? "bg-emerald-400"
    : vllmColor === "yellow"
      ? "bg-yellow-400 animate-pulse"
      : "bg-red-400";
  const vllmTextCls = vllmColor === "emerald"
    ? "text-emerald-400"
    : vllmColor === "yellow"
      ? "text-yellow-400"
      : "text-red-400";
  const vllmBarCls = vllmColor === "emerald"
    ? "bg-emerald-400"
    : vllmColor === "yellow"
      ? "bg-yellow-400"
      : "bg-red-400";

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
        setVllmStatus(r);
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
    setActionError("");
    try {
      await api.pipeline.stop();
      await api.pipeline.switchAdapter("disabled").catch(() => null);
      await api.localInference.vllm.stop().catch(() => null);
      await refreshVllm("http://localhost:8000").catch(() => null);
      setStatus(s => s ? { ...s, state: "stopped" } : s);
      setSwitchOpen(false);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to stop pipeline");
    } finally { setBusy(false); }
  }

  // ── Apply ─────────────────────────────────────────────────────────────────────
  async function applyAdapter() {
    setBusy(true);
    setActionError("");
    try {
      if (LOCAL_ADAPTERS.has(backend)) {
        if (backend === "vllm" && effectiveModel) {
          setVllmBusy(true);
          await api.localInference.vllm.start(effectiveVllmModel, resolvedUrl || undefined);
          await waitForVllmReady(resolvedUrl || undefined);
          setVllmBusy(false);
        }
        await api.pipeline.switchAdapter(
          backend, undefined, undefined,
          (backend === "ollama" || backend === "vllm") ? effectiveAdapterModel || undefined : undefined,
          resolvedUrl || undefined,
        );
      } else {
        await api.pipeline.switchAdapter(backend, resolvedUrl || undefined, nvidiaKey || undefined);
      }
      if (status?.adapter === "vllm" && backend !== "vllm") {
        await api.localInference.vllm.stop().catch(() => null);
        await refreshVllm("http://localhost:8000").catch(() => null);
      }
      setSwitchOpen(false);
      setProbe("idle");
      setStatus(s => s ? { ...s, state: "running", adapter: backend } : s);
    } catch (err) {
      setVllmBusy(false);
      setActionError(actionErrorMessage(err, "Failed to apply adapter"));
    } finally { setBusy(false); }
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

  const VllmReadiness = ({ compact = false }: { compact?: boolean }) => (
    <div
      className={cn(
        "rounded border border-border bg-background/60",
        compact ? "px-2 py-1 min-w-36" : "px-2.5 py-2 space-y-1.5"
      )}
    >
      <div className="flex items-center gap-1.5 min-w-0">
        <span className={cn("h-2 w-2 rounded-full shrink-0", vllmDotCls)} />
        <span className={cn("text-[10px] font-medium shrink-0", vllmTextCls)}>
          {vllmLabel}
        </span>
        {vllmStatus?.managed_model && !compact && (
          <span className="min-w-0 truncate text-[10px] font-mono text-muted-foreground/70">
            {vllmStatus.managed_model}
          </span>
        )}
      </div>
      <div className="h-1.5 rounded bg-muted overflow-hidden">
        <div
          className={cn("h-full transition-all", vllmBarCls)}
          style={{ width: `${vllmProgress}%` }}
        />
      </div>
      {!compact && vllmStatus?.managed_log_tail?.length ? (
        <pre className="max-h-16 overflow-y-auto whitespace-pre-wrap rounded bg-black/30 px-2 py-1 text-[10px] text-muted-foreground/70">
          {vllmStatus.managed_log_tail.slice(-4).join("\n")}
        </pre>
      ) : null}
    </div>
  );

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

          {recommendedModels.length > 0 && (
            <select
              value=""
              onChange={e => {
                if (!e.target.value) return;
                setSelectedModel("");
                setCustomModel(e.target.value);
              }}
              className="w-full rounded border border-input bg-background px-2 py-1.5 text-xs text-foreground"
            >
              <option value="">Presets: Cosmos / Gemma</option>
              {recommendedModels.map(m => (
                <option key={`${m.backend}:${m.name}`} value={m.name}>
                  {m.label} · {m.vram_gb} GB VRAM
                  {m.ram_gb ? ` · ${m.ram_gb} GB RAM` : ""}
                  {m.gated ? " · HF access required" : ""}
                </option>
              ))}
            </select>
          )}

          {/* Free-text override — type any model name not in the list */}
          <input
            type="text"
            placeholder={
              backend === "vllm"
                ? "or type: nvidia/cosmos3-nano-reasoner, google/gemma-4-E4B-it"
                : "or type: gemma4:e4b, gemma4:12b"
            }
            value={customModel}
            onChange={e => { setCustomModel(e.target.value); if (e.target.value) setSelectedModel(""); }}
            className="w-full rounded border border-input bg-background px-2 py-1.5 text-[10px] font-mono text-foreground placeholder:text-muted-foreground/30"
          />

          {selectedCatalogModel && (
            <div className="space-y-1">
              <p className="text-[10px] text-muted-foreground/50">
                {selectedCatalogModel.description} · {selectedCatalogModel.tier} tier
                {selectedCatalogModel.ram_gb ? ` · ${selectedCatalogModel.ram_gb} GB RAM` : ""}
                {selectedCatalogModel.launch_bin ? ` · ${selectedCatalogModel.launch_bin}` : ""}
              </p>
              {selectedCatalogModel.gated && (
                <p className="flex items-center gap-1 text-[10px] text-yellow-400">
                  <AlertTriangle className="h-3 w-3 shrink-0" />
                  {selectedCatalogModel.access_note ?? "Requires Hugging Face access."}
                </p>
              )}
            </div>
          )}

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

      {backend === "vllm" && (
        <div className="space-y-2">
          <VllmReadiness />
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={loadVllmOnly}
              disabled={vllmBusy || !effectiveModel || !resolvedUrl}
              className="flex items-center gap-1 rounded border border-border px-2.5 py-1 text-[10px] text-muted-foreground hover:text-foreground hover:border-primary/40 disabled:opacity-40 transition-colors"
            >
              {vllmBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
              {vllmBusy ? "Loading vLLM…" : vllmIsReady ? "Reload vLLM" : "Load vLLM"}
            </button>
            <button
              type="button"
              onClick={unloadVllm}
              disabled={vllmBusy || (!vllmStatus?.managed && !vllmStatus?.managed_state)}
              className="flex items-center gap-1 rounded border border-red-500/25 px-2.5 py-1 text-[10px] text-red-400/70 hover:text-red-400 hover:bg-red-500/10 disabled:opacity-40 transition-colors"
            >
              <Square className="h-3 w-3" />
              Unload vLLM
            </button>
          </div>
        </div>
      )}

      {actionError && (
        <p className="flex items-center gap-1.5 rounded border border-red-500/25 bg-red-500/10 px-2 py-1 text-[10px] text-red-400">
          <AlertTriangle className="h-3 w-3 shrink-0" />
          {actionError}
        </p>
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
          {busy
            ? (vllmBusy ? "Loading vLLM…" : "Starting…")
            : canApply
              ? (backend === "vllm" && !vllmIsReady ? "Load + Apply" : "Apply")
              : "Check first"}
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
      <VllmReadiness compact />
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
