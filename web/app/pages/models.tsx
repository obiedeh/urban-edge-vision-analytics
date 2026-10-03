import { useEffect, useMemo, useRef, useState } from "react";
import {
  api, apiErrorMessage,
  type CatalogModel, type HostCapabilities, type InferenceSettings, type ModelBackend,
  type ModelSettings, type ModelStatus, type PromptPreset, type VllmStatus,
} from "@/lib/api";
import { RuntimeStatusBar, useRuntimeStatus } from "@/components/runtime-status-bar";
import { ModelStateChip, StatusMsg } from "@/components/status-chip";
import { cn, inputCls, selectCls, btnPrimary, btnGhost, btnDanger, formatGb, formatMs, epochAge } from "@/lib/utils";
import {
  Cpu, Server, HardDrive, CheckCircle2, Star, Lock, Loader2, Play, Square, Save, RotateCcw, Eye, EyeOff, Terminal, Box,
} from "lucide-react";

// ── Host card ─────────────────────────────────────────────────────────────────

function HostCard({ host }: { host: HostCapabilities | null }) {
  if (!host) return <div className="rounded-lg border border-border bg-card p-4 h-28 snapshot-shimmer" />;
  const Flag = ({ ok, label }: { ok: boolean; label: string }) => (
    <span className={cn("inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px]", ok ? "border-emerald-500/30 text-emerald-400 bg-emerald-500/10" : "border-border text-muted-foreground")}>
      {ok ? <CheckCircle2 className="h-3 w-3" /> : <Square className="h-3 w-3" />} {label}
    </span>
  );
  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-2">
      <div className="flex items-center gap-2">
        <Server className="h-4 w-4 text-muted-foreground" />
        <span className="text-xs font-semibold text-foreground">Host</span>
        <span className="font-mono text-[10px] text-muted-foreground">{host.hostname} · {host.machine}</span>
        <span className="ml-auto rounded border border-primary/30 bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">{host.recommended_profile}</span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[11px]">
        <div>
          <div className="text-muted-foreground">{host.is_jetson ? "Jetson" : "GPU"}</div>
          <div className="text-foreground font-medium truncate" title={host.gpu_name ?? ""}>{host.is_jetson ? host.jetson_model : host.gpu_name ?? "none"}</div>
        </div>
        <div>
          <div className="text-muted-foreground">{host.unified_memory ? "Unified memory" : "VRAM free / total"}</div>
          <div className="text-foreground font-medium tabular-nums">
            {host.unified_memory ? formatGb(host.ram_available_gb) : `${formatGb(host.gpu_vram_free_gb)} / ${formatGb(host.gpu_vram_total_gb)}`}
          </div>
        </div>
        <div>
          <div className="text-muted-foreground">RAM available / total</div>
          <div className="text-foreground font-medium tabular-nums">{formatGb(host.ram_available_gb)} / {formatGb(host.ram_total_gb)}</div>
        </div>
        <div className="flex items-end gap-1 flex-wrap">
          <Flag ok={host.has_ollama} label="Ollama" />
          <Flag ok={host.has_vllm_binary} label="vLLM" />
          <Flag ok={host.has_docker} label="Docker" />
        </div>
      </div>
    </div>
  );
}

// ── Current model card ────────────────────────────────────────────────────────

function CurrentModelCard({ model }: { model: ModelStatus | null }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <Cpu className="h-4 w-4 text-muted-foreground" />
        <span className="text-xs font-semibold text-foreground">Current model</span>
        <ModelStateChip model={model} />
        {model && <span className="font-mono text-[11px] text-foreground/80 truncate">{model.backend}{model.model ? ` · ${model.model}` : ""}</span>}
        {model?.label && <span className="text-[10px] text-muted-foreground truncate">{model.label}</span>}
      </div>
      {model ? (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-[11px] tabular-nums">
            <div><div className="text-muted-foreground">endpoint</div><div className="font-mono text-foreground truncate" title={model.endpoint}>{model.endpoint || "—"}</div></div>
            <div><div className="text-muted-foreground">latency p50 / p95</div><div className="text-foreground">{formatMs(model.latency.p50_ms)} / {formatMs(model.latency.p95_ms)}</div></div>
            <div><div className="text-muted-foreground">calls / failures</div><div className="text-foreground">{model.total_calls} / <span className={model.total_failures ? "text-red-400" : ""}>{model.total_failures}</span></div></div>
            <div><div className="text-muted-foreground">consecutive failures</div><div className={cn("text-foreground", model.consecutive_failures > 0 && "text-red-400")}>{model.consecutive_failures}</div></div>
            <div><div className="text-muted-foreground">last OK</div><div className="text-foreground">{epochAge(model.last_ok_at)}</div></div>
          </div>
          {model.last_error && (
            <div className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-300 break-words">
              <span className="text-red-400/70">{epochAge(model.last_error_at)}: </span>{model.last_error}
            </div>
          )}
        </>
      ) : (
        <p className="text-xs text-muted-foreground">Runtime status unavailable.</p>
      )}
    </div>
  );
}

// ── Catalog ───────────────────────────────────────────────────────────────────

const TIER_CLS: Record<string, string> = {
  nano: "text-emerald-400 border-emerald-500/30",
  mid: "text-blue-300 border-blue-500/30",
  high: "text-yellow-400 border-yellow-500/30",
  max: "text-red-400 border-red-500/30",
};

function CatalogCard({
  m, current, busy, onUseOllama, onLoadVllm, onUseVllm, host,
}: {
  m: CatalogModel;
  current: ModelStatus | null;
  busy: boolean;
  host: HostCapabilities | null;
  onUseOllama: (m: CatalogModel) => void;
  onLoadVllm: (m: CatalogModel, launcher: "auto" | "binary" | "docker", modelPath: string) => void;
  onUseVllm: (m: CatalogModel) => void;
}) {
  const isCurrent = current && current.backend === m.backend && (current.model === m.name || current.model === m.hf_id || current.model === m.served_model_name);
  const blocked = !m.can_run;
  const defaultLauncher: "auto" | "binary" | "docker" = m.launcher === "docker" ? "docker" : "auto";
  const [launcher, setLauncher] = useState<"auto" | "binary" | "docker">(defaultLauncher);
  const [modelPath, setModelPath] = useState("");
  const effectiveLauncher = launcher === "auto" ? (host?.is_jetson ? "docker" : "binary") : launcher;

  return (
    <div className={cn("rounded-lg border bg-card p-3 space-y-2 flex flex-col", isCurrent ? "border-primary/60 ring-1 ring-primary/30" : "border-border", blocked && "opacity-60")}>
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-xs font-semibold text-foreground">{m.label}</span>
            {m.recommended && <span title="Recommended for this host" className="inline-flex items-center gap-0.5 rounded border border-primary/40 bg-primary/10 px-1 text-[9px] text-primary"><Star className="h-2.5 w-2.5" /> recommended</span>}
            {m.installed && <span className="rounded border border-emerald-500/30 bg-emerald-500/10 px-1 text-[9px] text-emerald-400">installed</span>}
            {m.gated && <span title={m.access_note ?? "Gated Hugging Face repo"} className="inline-flex items-center gap-0.5 rounded border border-yellow-500/30 bg-yellow-500/10 px-1 text-[9px] text-yellow-400"><Lock className="h-2.5 w-2.5" /> gated</span>}
            {isCurrent && <span className="rounded border border-primary/40 bg-primary/15 px-1 text-[9px] text-primary">in use</span>}
          </div>
          <div className="font-mono text-[10px] text-muted-foreground/70 truncate" title={m.hf_id ?? m.name}>{m.name}</div>
        </div>
        <span className={cn("rounded border px-1 py-0.5 text-[9px] font-semibold uppercase", TIER_CLS[m.tier] ?? "")}>{m.tier}</span>
      </div>
      <div className="flex items-center gap-3 text-[10px] text-muted-foreground tabular-nums flex-wrap">
        <span className="rounded bg-secondary/60 px-1.5 py-0.5 font-mono">{m.backend}</span>
        <span>{m.params_b} B params</span>
        <span>~{m.vram_gb} GB {host?.unified_memory ? "mem" : "VRAM"}</span>
        {m.ram_gb ? <span>{m.ram_gb} GB RAM</span> : null}
      </div>
      <p className="text-[11px] text-muted-foreground/90 leading-snug flex-1">{m.description}</p>
      {blocked && (
        <ul className="text-[10px] text-red-300/90 space-y-0.5">
          {m.blocked_reasons.map((r) => <li key={r}>• {r}</li>)}
        </ul>
      )}
      {m.backend === "ollama" && (
        <div className="space-y-1.5">
          {!m.installed && (
            <div className="flex items-center gap-1.5 rounded bg-black/40 px-2 py-1 font-mono text-[10px] text-foreground/70"><Terminal className="h-3 w-3 shrink-0" /> {m.pull_cmd}</div>
          )}
          <button onClick={() => onUseOllama(m)} disabled={busy || blocked || !m.installed} className={cn(m.installed ? btnPrimary : btnGhost, "py-1")} title={!m.installed ? "Pull the model first" : undefined}>
            <Play className="h-3 w-3" /> {isCurrent ? "In use" : "Use"}
          </button>
        </div>
      )}
      {m.backend === "vllm" && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 flex-wrap">
            <select value={launcher} onChange={(e) => setLauncher(e.target.value as typeof launcher)} disabled={busy} className={cn(selectCls, "w-auto py-1")}>
              <option value="auto">launcher: auto ({host?.is_jetson ? "docker" : "binary"})</option>
              <option value="binary">launcher: vllm binary</option>
              <option value="docker">launcher: docker</option>
            </select>
            {effectiveLauncher === "docker" && (
              <input value={modelPath} onChange={(e) => setModelPath(e.target.value)} placeholder="model_path (host dir with weights, optional)" className={cn(inputCls, "flex-1 min-w-[180px] py-1 font-mono")} disabled={busy} />
            )}
          </div>
          <div className="flex items-center gap-1.5 flex-wrap">
            <button onClick={() => onLoadVllm(m, launcher, modelPath)} disabled={busy || blocked} className={cn(btnPrimary, "py-1")}>
              <Play className="h-3 w-3" /> Load &amp; use
            </button>
            <button onClick={() => onUseVllm(m)} disabled={busy} className={cn(btnGhost, "py-1")} title="Select without starting a server — for a vLLM server that is already running">
              Use (already running)
            </button>
          </div>
          {!m.installed && <div className="flex items-center gap-1.5 rounded bg-black/40 px-2 py-1 font-mono text-[10px] text-foreground/60"><Terminal className="h-3 w-3 shrink-0" /> {m.pull_cmd}</div>}
        </div>
      )}
    </div>
  );
}

// ── Managed vLLM panel ────────────────────────────────────────────────────────

function ManagedVllmPanel({ status, onStop, busy, pendingMsg }: { status: VllmStatus | null; onStop: () => void; busy: boolean; pendingMsg: string | null }) {
  const logRef = useRef<HTMLPreElement | null>(null);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [status?.managed_log_tail?.length]);
  const state = status?.managed_state ?? null;
  const dot = status?.running ? "bg-emerald-400" : state === "starting" ? "bg-yellow-400 animate-pulse" : state === "failed" ? "bg-red-400" : "bg-muted-foreground/40";
  const label = status?.running ? "running" : state === "starting" ? "starting (loading weights)" : state === "failed" ? "failed" : "stopped";
  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <Box className="h-4 w-4 text-muted-foreground" />
        <span className="text-xs font-semibold text-foreground">Managed vLLM server</span>
        <span className={cn("h-2 w-2 rounded-full", dot)} />
        <span className="text-[11px] text-foreground/80">{label}</span>
        {status?.managed_model && <span className="font-mono text-[10px] text-muted-foreground truncate">{status.managed_model}</span>}
        {status?.managed_pid != null && <span className="font-mono text-[10px] text-muted-foreground">pid {status.managed_pid}</span>}
        {status?.endpoint && <span className="font-mono text-[10px] text-muted-foreground">{status.endpoint}</span>}
        {status?.running && <span className="text-[10px] text-muted-foreground">{status.model_count} model{status.model_count === 1 ? "" : "s"} loaded</span>}
        <button onClick={onStop} disabled={busy || (!status?.managed && state === null)} className={cn(btnDanger, "ml-auto py-1")}>
          {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Square className="h-3 w-3" />} Stop
        </button>
      </div>
      {pendingMsg && <div className="flex items-center gap-2 text-[11px] text-yellow-300"><Loader2 className="h-3 w-3 animate-spin" /> {pendingMsg}</div>}
      {(status?.managed_log_tail?.length ?? 0) > 0 ? (
        <pre ref={logRef} className="max-h-48 overflow-y-auto overflow-x-auto rounded bg-black/50 border border-border px-3 py-2 text-[10px] font-mono text-foreground/70 whitespace-pre-wrap">
          {status!.managed_log_tail.slice(-200).join("\n")}
        </pre>
      ) : (
        <p className="text-[11px] text-muted-foreground">No managed server. "Load &amp; use" on a vLLM catalog entry starts one here; its log tail appears below.</p>
      )}
    </div>
  );
}

// ── Endpoint editor ───────────────────────────────────────────────────────────

function EndpointEditor({ onSaved }: { onSaved: () => void }) {
  const [form, setForm] = useState<ModelSettings | null>(null);
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => { api.settings.model().then((s) => setForm({ ...s, api_key: "" })).catch((e) => setMsg({ kind: "err", text: apiErrorMessage(e) })); }, []);

  async function save() {
    if (!form) return;
    setSaving(true); setMsg(null);
    try {
      const saved = await api.settings.putModel(form);
      setForm({ ...saved, api_key: "" });
      setMsg({ kind: "ok", text: "Model settings saved and applied." });
      onSaved();
    } catch (e) { setMsg({ kind: "err", text: apiErrorMessage(e, "Save failed") }); }
    finally { setSaving(false); }
  }

  async function resetDefault() {
    setMsg(null);
    try {
      const d = await api.settings.modelDefault();
      setForm((f) => f ? { ...f, ...d.default, api_key: "" } as ModelSettings : f);
      setMsg({ kind: "ok", text: `Host default loaded (${d.default.label ?? d.default.model}). Save to apply.` });
    } catch (e) { setMsg({ kind: "err", text: apiErrorMessage(e) }); }
  }

  if (!form) return <div className="rounded-lg border border-border bg-card p-4 h-40 snapshot-shimmer" />;
  const set = <K extends keyof ModelSettings>(k: K, v: ModelSettings[K]) => setForm((f) => (f ? { ...f, [k]: v } : f));
  const placeholderEp = { vllm: "http://localhost:8000", ollama: "http://localhost:11434", nim: "https://integrate.api.nvidia.com", mock: "" }[form.backend];

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <HardDrive className="h-4 w-4 text-muted-foreground" />
        <span className="text-xs font-semibold text-foreground">Model endpoint</span>
        <span className="text-[10px] text-muted-foreground">PUT /settings/model — applied live, no restart</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        <label className="space-y-1 text-xs text-muted-foreground">Backend
          <select value={form.backend} onChange={(e) => set("backend", e.target.value as ModelBackend)} className={selectCls}>
            <option value="ollama">Ollama</option>
            <option value="vllm">vLLM (OpenAI-compatible)</option>
            <option value="nim">NVIDIA NIM (cloud / local, API key)</option>
            <option value="mock">Mock (synthetic detections, no model)</option>
          </select>
        </label>
        <label className="space-y-1 text-xs text-muted-foreground">Endpoint
          <input value={form.endpoint} onChange={(e) => set("endpoint", e.target.value)} placeholder={placeholderEp || "(not used)"} disabled={form.backend === "mock"} className={cn(inputCls, "font-mono")} />
        </label>
        <label className="space-y-1 text-xs text-muted-foreground">Model
          <input value={form.model} onChange={(e) => set("model", e.target.value)} placeholder={form.backend === "ollama" ? "gemma4:e4b" : form.backend === "vllm" ? "nvidia/cosmos-reason2-2b" : form.backend === "nim" ? "nvidia/cosmos-reason2-2b" : "(not used)"} disabled={form.backend === "mock"} className={cn(inputCls, "font-mono")} />
        </label>
        {form.backend === "nim" && (
          <label className="space-y-1 text-xs text-muted-foreground">API key {form.has_api_key && <span className="text-emerald-400/80">(stored — blank keeps it)</span>}
            <div className="relative">
              <input type={showKey ? "text" : "password"} value={form.api_key} onChange={(e) => set("api_key", e.target.value)} placeholder={form.has_api_key ? "(unchanged)" : "nvapi-…"} className={cn(inputCls, "pr-8 font-mono")} autoComplete="off" />
              <button type="button" onClick={() => setShowKey((v) => !v)} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">{showKey ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}</button>
            </div>
          </label>
        )}
        <label className="space-y-1 text-xs text-muted-foreground">Max tokens
          <input type="number" min={32} max={8192} value={form.max_tokens} onChange={(e) => set("max_tokens", parseInt(e.target.value) || 512)} className={inputCls} />
        </label>
        <label className="space-y-1 text-xs text-muted-foreground">Timeout (s)
          <input type="number" min={5} max={600} step={5} value={form.timeout_s} onChange={(e) => set("timeout_s", parseFloat(e.target.value) || 60)} className={inputCls} />
        </label>
        <label className="space-y-1 text-xs text-muted-foreground">Label (display)
          <input value={form.label} onChange={(e) => set("label", e.target.value)} className={inputCls} />
        </label>
        <label className="flex items-center gap-2 text-xs text-muted-foreground self-end pb-1.5">
          <input type="checkbox" checked={form.think} onChange={(e) => set("think", e.target.checked)} className="rounded border-input bg-background" />
          Enable thinking / reasoning mode (slower)
        </label>
      </div>
      {msg && <StatusMsg kind={msg.kind} text={msg.text} />}
      <div className="flex items-center gap-2 flex-wrap">
        <button onClick={save} disabled={saving} className={btnPrimary}>{saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />} Save &amp; apply</button>
        <button onClick={resetDefault} disabled={saving} className={btnGhost}><RotateCcw className="h-3 w-3" /> Reset to host default</button>
      </div>
    </div>
  );
}

// ── Inference settings ────────────────────────────────────────────────────────

function InferenceSettingsForm() {
  const [form, setForm] = useState<InferenceSettings | null>(null);
  const [presets, setPresets] = useState<PromptPreset[]>([]);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    api.settings.inference().then(setForm).catch((e) => setMsg({ kind: "err", text: apiErrorMessage(e) }));
    api.settings.promptPresets().then(setPresets).catch(() => setPresets([]));
  }, []);

  async function save() {
    if (!form) return;
    setSaving(true); setMsg(null);
    try { setForm(await api.settings.putInference(form)); setMsg({ kind: "ok", text: "Inference settings applied." }); }
    catch (e) { setMsg({ kind: "err", text: apiErrorMessage(e, "Save failed") }); }
    finally { setSaving(false); }
  }

  if (!form) return <div className="rounded-lg border border-border bg-card p-4 h-40 snapshot-shimmer" />;
  const set = <K extends keyof InferenceSettings>(k: K, v: InferenceSettings[K]) => setForm((f) => (f ? { ...f, [k]: v } : f));
  const preset = presets.find((p) => p.id === form.prompt_preset);

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Cpu className="h-4 w-4 text-muted-foreground" />
        <span className="text-xs font-semibold text-foreground">Inference settings</span>
        <span className="text-[10px] text-muted-foreground">PUT /settings/inference — video keeps native fps; this only sets the inference cadence</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        <label className="space-y-1 text-xs text-muted-foreground sm:col-span-2 lg:col-span-1">
          Interval between inferences: <b className="text-foreground tabular-nums">{form.interval_ms} ms</b> ({(1000 / form.interval_ms).toFixed(2)} Hz)
          <div className="flex items-center gap-2">
            <input type="range" min={100} max={10000} step={100} value={Math.min(form.interval_ms, 10000)} onChange={(e) => set("interval_ms", parseInt(e.target.value))} className="flex-1 accent-[hsl(var(--primary))]" />
            <input type="number" min={100} max={60000} step={100} value={form.interval_ms} onChange={(e) => set("interval_ms", Math.min(60000, Math.max(100, parseInt(e.target.value) || 1000)))} className={cn(inputCls, "w-24")} />
          </div>
        </label>
        <label className="space-y-1 text-xs text-muted-foreground">Inference frame width
          <input type="number" min={160} max={1920} step={16} value={form.width} onChange={(e) => set("width", parseInt(e.target.value) || 640)} className={inputCls} />
        </label>
        <label className="space-y-1 text-xs text-muted-foreground">Inference frame height
          <input type="number" min={120} max={1080} step={16} value={form.height} onChange={(e) => set("height", parseInt(e.target.value) || 360)} className={inputCls} />
        </label>
        <label className="space-y-1 text-xs text-muted-foreground">Prompt preset
          <select value={form.prompt_preset} onChange={(e) => set("prompt_preset", e.target.value)} className={selectCls}>
            {presets.length === 0 && <option value={form.prompt_preset}>{form.prompt_preset}</option>}
            {presets.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
          {preset && <span className="block text-[10px] text-muted-foreground/70">{preset.description}{preset.focus ? ` — focus: ${preset.focus}` : ""}</span>}
        </label>
        <label className="space-y-1 text-xs text-muted-foreground">Stream JPEG quality ({form.jpeg_quality})
          <input type="range" min={40} max={95} value={form.jpeg_quality} onChange={(e) => set("jpeg_quality", parseInt(e.target.value))} className="w-full accent-[hsl(var(--primary))]" />
        </label>
        <label className="space-y-1 text-xs text-muted-foreground">Display max width (px)
          <input type="number" min={320} max={3840} step={16} value={form.display_max_width} onChange={(e) => set("display_max_width", parseInt(e.target.value) || 1280)} className={inputCls} />
        </label>
      </div>
      {msg && <StatusMsg kind={msg.kind} text={msg.text} />}
      <button onClick={save} disabled={saving} className={btnPrimary}>{saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />} Save &amp; apply</button>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function ModelsPage() {
  const { status: runtime } = useRuntimeStatus(2000);
  const [catalog, setCatalog] = useState<CatalogModel[]>([]);
  const [catalogHost, setCatalogHost] = useState<HostCapabilities | null>(null);
  const [catalogErr, setCatalogErr] = useState<string | null>(null);
  const [backendFilter, setBackendFilter] = useState<"all" | "ollama" | "vllm">("all");
  const [showBlocked, setShowBlocked] = useState(true);
  const [vllm, setVllm] = useState<VllmStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [settingsVersion, setSettingsVersion] = useState(0);

  const vllmEndpoint = runtime?.model?.backend === "vllm" ? runtime.model.endpoint : undefined;

  async function loadCatalog() {
    try { const r = await api.inference.catalog(); setCatalog(r.models); setCatalogHost(r.host); setCatalogErr(null); }
    catch (e) { setCatalogErr(apiErrorMessage(e, "Catalog unavailable")); }
  }
  useEffect(() => { void loadCatalog(); }, [settingsVersion]);

  useEffect(() => {
    let dead = false;
    const tick = async () => {
      try { const s = await api.inference.vllm.status(vllmEndpoint); if (!dead) setVllm(s); }
      catch { if (!dead) setVllm(null); }
    };
    tick();
    const t = setInterval(tick, 3000);
    return () => { dead = true; clearInterval(t); };
  }, [vllmEndpoint]);

  const host = runtime?.host ?? catalogHost;
  const filtered = useMemo(
    () => catalog.filter((m) => (backendFilter === "all" || m.backend === backendFilter) && (showBlocked || m.can_run)),
    [catalog, backendFilter, showBlocked]
  );

  async function useOllama(m: CatalogModel) {
    setBusy(true); setActionMsg(null);
    try {
      await api.inference.apply({ backend: "ollama", model: m.name, label: m.label });
      setActionMsg({ kind: "ok", text: `Now using ${m.label} via Ollama.` });
      setSettingsVersion((v) => v + 1);
    } catch (e) { setActionMsg({ kind: "err", text: apiErrorMessage(e, "Apply failed") }); }
    finally { setBusy(false); }
  }

  async function useVllm(m: CatalogModel) {
    setBusy(true); setActionMsg(null);
    try {
      await api.inference.apply({ backend: "vllm", model: m.served_model_name ?? m.name, label: m.label, endpoint: vllm?.endpoint ?? "" });
      setActionMsg({ kind: "ok", text: `Now using ${m.label} on the running vLLM server.` });
      setSettingsVersion((v) => v + 1);
    } catch (e) { setActionMsg({ kind: "err", text: apiErrorMessage(e, "Apply failed") }); }
    finally { setBusy(false); }
  }

  async function loadVllm(m: CatalogModel, launcher: "auto" | "binary" | "docker", modelPath: string) {
    setBusy(true); setActionMsg(null);
    try {
      const res = await api.inference.vllm.start({ model: m.name, endpoint: "http://localhost:8000", launcher, model_path: modelPath || undefined, apply: true });
      if (res.state === "failed") throw new Error(`vLLM failed to start: ${res.log_tail.slice(-3).join(" | ")}`);
      setPending(`Starting vLLM (${res.launcher ?? launcher}) for ${m.label}; polling readiness…`);
      setSettingsVersion((v) => v + 1);
      const deadline = Date.now() + 15 * 60 * 1000;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 3000));
        const s = await api.inference.vllm.status(res.endpoint ?? undefined);
        setVllm(s);
        if (s.running) { setActionMsg({ kind: "ok", text: `vLLM is serving ${m.label}; inference now uses it.` }); break; }
        if (s.managed_state === "failed") throw new Error(`vLLM exited while loading. Last log lines: ${s.managed_log_tail.slice(-3).join(" | ")}`);
      }
    } catch (e) { setActionMsg({ kind: "err", text: apiErrorMessage(e, "vLLM start failed") }); }
    finally { setBusy(false); setPending(null); }
  }

  const [stopArmed, setStopArmed] = useState(false);
  async function stopVllm() {
    // Two-step: the server may be serving another app on this device.
    if (!stopArmed) {
      setStopArmed(true);
      setActionMsg({ kind: "err", text: "Stopping the model server affects every app using it. Press Stop again to confirm." });
      return;
    }
    setStopArmed(false);
    setBusy(true); setActionMsg(null);
    try { setVllm((prev) => prev ? { ...prev, managed_state: "stopped", running: false } : prev); await api.inference.vllm.stop(); setActionMsg({ kind: "ok", text: "Managed vLLM server stopped. Inference will report unavailable until another model is selected." }); }
    catch (e) { setActionMsg({ kind: "err", text: apiErrorMessage(e, "Stop failed") }); }
    finally { setBusy(false); }
  }

  return (
    <div className="space-y-0">
      <RuntimeStatusBar status={runtime} />
      <div className="p-4 space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <h1 className="text-lg font-semibold">Models</h1>
          <span className="text-xs text-muted-foreground">Model selection and inference cadence apply live to every camera.</span>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <HostCard host={host} />
          <CurrentModelCard model={runtime?.model ?? null} />
        </div>

        {actionMsg && <StatusMsg kind={actionMsg.kind} text={actionMsg.text} />}

        <div className="space-y-2">
          <div className="flex items-center gap-3 flex-wrap">
            <h2 className="text-sm font-semibold text-foreground">Catalog</h2>
            <div className="flex items-center gap-1">
              {(["all", "ollama", "vllm"] as const).map((b) => (
                <button key={b} onClick={() => setBackendFilter(b)} className={cn("rounded border px-2 py-0.5 text-[11px]", backendFilter === b ? "border-primary/50 bg-primary/15 text-foreground" : "border-border text-muted-foreground hover:text-foreground")}>{b}</button>
              ))}
            </div>
            <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <input type="checkbox" checked={showBlocked} onChange={(e) => setShowBlocked(e.target.checked)} className="rounded border-input bg-background" /> show blocked
            </label>
            <span className="text-[10px] text-muted-foreground/70 ml-auto">
              Blocked = memory preflight failed on this host ({host?.unified_memory ? formatGb(host.ram_available_gb) + " available" : formatGb(host?.gpu_vram_free_gb) + " free VRAM"}).
            </span>
          </div>
          {catalogErr && <StatusMsg kind="err" text={catalogErr} />}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {filtered.map((m) => (
              <CatalogCard key={`${m.backend}:${m.name}`} m={m} current={runtime?.model ?? null} busy={busy} host={host} onUseOllama={useOllama} onLoadVllm={loadVllm} onUseVllm={useVllm} />
            ))}
            {filtered.length === 0 && !catalogErr && <p className="text-xs text-muted-foreground">No catalog entries match the filter.</p>}
          </div>
        </div>

        <ManagedVllmPanel status={vllm} onStop={stopVllm} busy={busy} pendingMsg={pending} />

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <EndpointEditor key={settingsVersion} onSaved={() => setSettingsVersion((v) => v + 1)} />
          <InferenceSettingsForm />
        </div>
      </div>
    </div>
  );
}
