import { useEffect, useState } from "react";
import {
  api,
  type Camera,
  type CameraConfigPayload,
  type CameraConfigResponse,
  type CameraTestResponse,
  ApiError,
} from "@/lib/api";
import {
  Save, Eye, EyeOff, Trash2, CheckCircle, AlertCircle,
  Camera as CameraIcon, Wifi, WifiOff, Loader2, Square,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Constants ─────────────────────────────────────────────────────────────────

const MODEL_TYPES = [
  { value: "hikvision",     label: "Hikvision" },
  { value: "tapo",          label: "TP-Link Tapo" },
  { value: "dahua",         label: "Dahua" },
  { value: "amcrest",       label: "Amcrest" },
  { value: "axis",          label: "Axis" },
  { value: "reolink",       label: "Reolink" },
  { value: "generic_rtsp",  label: "Generic RTSP" },
  { value: "unifi_protect", label: "UniFi Protect" },
  { value: "http_mjpeg",    label: "HTTP MJPEG" },
];

const ADAPTERS = [
  { value: "mock",           label: "Mock (synthetic — no GPU)", hint: "Generates fake detections. Works without a real camera or NVIDIA hardware." },
  { value: "nvidia-nim",     label: "NVIDIA NIM",                hint: "NVIDIA Inference Microservice endpoint. Requires an endpoint URL and API key." },
  { value: "nvidia-vss",     label: "NVIDIA VSS",                hint: "NVIDIA Video Search and Summarization service." },
  { value: "nvidia-cosmos",  label: "NVIDIA Cosmos",             hint: "NVIDIA Cosmos world-model (vision-language)." },
  { value: "disabled",       label: "Disabled — stop pipeline",  hint: "Stop the inference pipeline. Camera config is kept on disk." },
];

const NEEDS_ENDPOINT = new Set(["nvidia-nim", "nvidia-vss", "nvidia-cosmos"]);

const DEFAULT_FORM: CameraConfigPayload = {
  camera_id: "",
  model_type: "hikvision",
  host: "",
  port: 554,
  stream: "01",
  channel: 1,
  username: "",
  password: "",
  rtsp_transport: "tcp",
  detection_adapter: "mock",
  nvidia_endpoint: "",
  nvidia_api_key: "",
  synthetic: false,
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="block text-xs font-medium text-muted-foreground">{label}</label>
      {children}
      {hint && <p className="text-[10px] text-muted-foreground/60">{hint}</p>}
    </div>
  );
}

function StatusMsg({ kind, text }: { kind: "ok" | "err" | "warn"; text: string }) {
  const styles = {
    ok:   "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
    err:  "bg-red-500/10 text-red-400 border-red-500/30",
    warn: "bg-yellow-500/10 text-yellow-400 border-yellow-500/30",
  }[kind];
  const Icon = kind === "ok" ? CheckCircle : AlertCircle;
  return (
    <div className={cn("flex items-center gap-2 rounded px-3 py-2 text-xs border", styles)}>
      <Icon className="h-3.5 w-3.5 shrink-0" />
      {text}
    </div>
  );
}

function TestResultBadge({ result }: { result: CameraTestResponse }) {
  if (result.ok) {
    return (
      <div className="flex items-start gap-2 rounded border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-400">
        <Wifi className="h-3.5 w-3.5 mt-0.5 shrink-0" />
        <div>
          <span className="font-medium">Reachable</span>
          {result.masked_url && (
            <p className="mt-0.5 font-mono text-[10px] text-emerald-400/70 break-all">{result.masked_url}</p>
          )}
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-start gap-2 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
      <WifiOff className="h-3.5 w-3.5 mt-0.5 shrink-0" />
      <div>
        <span className="font-medium">
          {result.stage === "reachability" ? "Host not reachable" : result.error ?? "Validation failed"}
        </span>
        {result.reach_error && (
          <p className="mt-0.5 font-mono text-[10px] text-red-400/70">{result.reach_error}</p>
        )}
        {result.masked_url && (
          <p className="mt-0.5 font-mono text-[10px] text-red-400/70 break-all">URL: {result.masked_url}</p>
        )}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  onSaved?: (res: CameraConfigResponse) => void;
  onDeleted?: () => void;
  /** When provided, seeds the form from this sidebar camera entry.
   *  If its ID matches the on-disk config, full credentials are loaded;
   *  otherwise only profile / adapter are prefilled. */
  prefillCamera?: Camera;
}

export function CameraConfigForm({ onSaved, onDeleted, prefillCamera }: Props) {
  const [form, setForm] = useState<CameraConfigPayload>(DEFAULT_FORM);
  const [showPassword, setShowPassword] = useState(false);
  const [showNvidiaKey, setShowNvidiaKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [saveStatus, setSaveStatus] = useState<{ kind: "ok" | "err" | "warn"; text: string } | null>(null);
  const [testResult, setTestResult] = useState<CameraTestResponse | null>(null);
  const [hasExisting, setHasExisting] = useState(false);

  useEffect(() => {
    api.cameras.getConfig().then((cfg) => {
      // If prefillCamera targets a different camera than the on-disk config,
      // start from a blank form seeded with just what the sidebar knows.
      if (prefillCamera && cfg.camera_id !== prefillCamera.id) {
        setHasExisting(false);
        setForm({
          ...DEFAULT_FORM,
          camera_id:         prefillCamera.id,
          model_type:        prefillCamera.profile ?? "hikvision",
          detection_adapter: prefillCamera.detection_adapter ?? "mock",
          synthetic:         prefillCamera.synthetic ?? false,
        });
        return;
      }
      // On-disk config matches (or no prefill) — load full details.
      setHasExisting(true);
      setForm({
        camera_id:         cfg.camera_id ?? "",
        model_type:        cfg.model_type ?? "hikvision",
        host:              cfg.host ?? "",
        port:              cfg.port ?? 554,
        stream:            cfg.stream ?? "01",
        channel:           cfg.channel ?? 1,
        username:          cfg.username ?? "",
        password:          "",
        rtsp_transport:    cfg.rtsp_transport ?? "tcp",
        detection_adapter: cfg.detection_adapter ?? "mock",
        nvidia_endpoint:   cfg.nvidia_endpoint ?? "",
        nvidia_api_key:    "",
        synthetic:         cfg.synthetic ?? false,
      });
    }).catch(() => {
      // No config on disk at all
      setHasExisting(false);
      if (prefillCamera) {
        setForm({
          ...DEFAULT_FORM,
          camera_id:         prefillCamera.id,
          model_type:        prefillCamera.profile ?? "hikvision",
          detection_adapter: prefillCamera.detection_adapter ?? "mock",
          synthetic:         prefillCamera.synthetic ?? false,
        });
      }
    });
  // Re-run whenever we switch to editing a different camera
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefillCamera?.id]);

  function set<K extends keyof CameraConfigPayload>(key: K, value: CameraConfigPayload[K]) {
    setForm((p) => ({ ...p, [key]: value }));
    setSaveStatus(null);
    setTestResult(null);
  }

  // ── Test ────────────────────────────────────────────────────────────────────
  async function testConnection() {
    if (form.synthetic) { setSaveStatus({ kind: "warn", text: "Synthetic cameras have no network connection to test." }); return; }
    if (!form.host.trim()) { setSaveStatus({ kind: "err", text: "Enter an IP address first." }); return; }
    setTesting(true); setTestResult(null); setSaveStatus(null);
    try {
      setTestResult(await api.cameras.testConfig({ ...form, host: form.host.trim() }));
    } catch (e) {
      setSaveStatus({ kind: "err", text: e instanceof Error ? e.message : "Test failed" });
    } finally { setTesting(false); }
  }

  // ── Save ────────────────────────────────────────────────────────────────────
  async function save() {
    if (!form.synthetic && !form.host.trim()) { setSaveStatus({ kind: "err", text: "Camera IP address is required for live cameras." }); return; }
    if (!form.synthetic && hostLooksDashed) { setSaveStatus({ kind: "err", text: "IP address uses dashes — use dots (192.168.1.249)." }); return; }
    setSaving(true); setSaveStatus(null);
    try {
      const res = await api.cameras.saveConfig({
        ...form,
        camera_id: form.camera_id?.trim() || undefined,
        host: form.host.trim(),
      });
      setHasExisting(true);
      setForm((p) => ({ ...p, camera_id: res.camera_id, password: "", nvidia_api_key: "" }));
      const adapterLabel = ADAPTERS.find(a => a.value === form.detection_adapter)?.label ?? form.detection_adapter;
      const pipelineNote = form.detection_adapter === "disabled"
        ? "Pipeline stopped."
        : `Pipeline started (${adapterLabel}).`;
      setSaveStatus({ kind: "ok", text: `"${res.camera_id}" saved. ${pipelineNote}` });
      onSaved?.(res);
    } catch (e) {
      const msg = e instanceof ApiError
        ? (() => { const d = e.detail?.detail ?? e.detail; return typeof d === "string" ? d : JSON.stringify(d); })()
        : e instanceof Error ? e.message : "Save failed";
      setSaveStatus({ kind: "err", text: msg });
    } finally { setSaving(false); }
  }

  // ── Stop pipeline only ──────────────────────────────────────────────────────
  async function stopPipeline() {
    setStopping(true); setSaveStatus(null);
    try {
      await api.pipeline.stop();
      // Also persist "disabled" in config file so it doesn't auto-restart on next boot
      if (hasExisting) {
        await api.pipeline.switchAdapter("disabled");
        setForm((p) => ({ ...p, detection_adapter: "disabled" }));
      }
      setSaveStatus({ kind: "warn", text: "Pipeline stopped. Adapter set to disabled." });
    } catch (e) {
      setSaveStatus({ kind: "err", text: e instanceof Error ? e.message : "Stop failed" });
    } finally { setStopping(false); }
  }

  // ── Delete config ───────────────────────────────────────────────────────────
  async function remove() {
    if (!window.confirm("Remove configs/camera.local.json and stop the pipeline?\n\nThe camera entry stays in the database until the next server restart.")) return;
    setDeleting(true); setSaveStatus(null);
    try {
      await api.cameras.deleteConfig();
      setHasExisting(false);
      setForm(DEFAULT_FORM);
      setTestResult(null);
      setSaveStatus({ kind: "ok", text: "Camera config removed and pipeline stopped." });
      onDeleted?.();
    } catch (e) {
      setSaveStatus({ kind: "err", text: e instanceof Error ? e.message : "Delete failed" });
    } finally { setDeleting(false); }
  }

  const busy = saving || deleting || testing || stopping;
  const selectedAdapter = ADAPTERS.find(a => a.value === form.detection_adapter);
  const needsNvidia = NEEDS_ENDPOINT.has(form.detection_adapter);
  const isSynthetic = form.synthetic ?? false;
  // Warn if host looks like an IP with dashes instead of dots (e.g. 192-168-1-1)
  const hostLooksDashed = !isSynthetic && /^\d+(-\d+){3}$/.test(form.host.trim());

  const inputCls = "w-full rounded border border-input bg-background px-2 py-1.5 text-xs text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50 disabled:opacity-50";
  const selectCls = "w-full rounded border border-input bg-background px-2 py-1.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50 disabled:opacity-50";

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center gap-2 flex-wrap">
        <CameraIcon className="h-4 w-4 text-muted-foreground shrink-0" />
        <span className="text-xs font-semibold text-foreground">
          {prefillCamera
            ? `Update Camera: ${prefillCamera.name || prefillCamera.id}`
            : hasExisting
            ? "Edit Camera Connection"
            : "Add Camera"}
        </span>
        {hasExisting && (
          <span className="text-[10px] px-1.5 py-0.5 rounded border border-emerald-500/30 bg-emerald-500/10 text-emerald-400">
            Config on disk
          </span>
        )}
        {prefillCamera && !hasExisting && (
          <span className="text-[10px] px-1.5 py-0.5 rounded border border-yellow-500/30 bg-yellow-500/10 text-yellow-400">
            No config file — enter credentials to create one
          </span>
        )}
      </div>

      {/* ── Camera mode selector ── */}
      <div className="flex items-center gap-1 p-1 rounded-lg bg-secondary/30 border border-border w-fit">
        <button
          type="button"
          onClick={() => set("synthetic", false)}
          disabled={busy}
          className={cn(
            "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all",
            !isSynthetic
              ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/40 shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          <span className="text-[10px]">📷</span>
          Live Camera
        </button>
        <button
          type="button"
          onClick={() => set("synthetic", true)}
          disabled={busy}
          className={cn(
            "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all",
            isSynthetic
              ? "bg-yellow-500/15 text-yellow-400 border border-yellow-500/40 shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          <span className="text-[10px]">🎭</span>
          Synthetic / Demo
        </button>
      </div>
      {isSynthetic ? (
        <p className="text-[11px] text-muted-foreground/70 -mt-3">
          No physical camera required — the pipeline generates synthetic detections. Good for demos and development.
        </p>
      ) : (
        <p className="text-[11px] text-muted-foreground/70 -mt-3">
          Reads a real RTSP stream from the camera. Detection can still use the mock adapter (no GPU required).
        </p>
      )}

      {/* ── Section 1: Camera ID (always visible) ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Field label="Camera Model" hint="Sets the RTSP URL path template">
          <select value={form.model_type} onChange={e => set("model_type", e.target.value)} disabled={busy} className={selectCls}>
            {MODEL_TYPES.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        </Field>

        <Field label="Camera ID" hint="Auto-generated from host if left blank">
          <input type="text"
            placeholder={isSynthetic ? `${form.model_type}-synthetic` : `${form.model_type}-${(form.host || "192-168-1-50").replace(/\./g, "-")}`}
            value={form.camera_id ?? ""} onChange={e => set("camera_id", e.target.value)} disabled={busy} className={inputCls} />
        </Field>
      </div>

      {/* ── Section 2: Camera Connection (live cameras only) ── */}
      {!isSynthetic && (
        <div>
          <p className="text-[10px] uppercase tracking-widest text-muted-foreground/60 mb-3">Camera Connection</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field
              label="IP Address"
              hint={hostLooksDashed
                ? undefined
                : "Camera IP address or hostname on your network"}
            >
              <input type="text" placeholder="192.168.1.50" value={form.host}
                onChange={e => set("host", e.target.value)} disabled={busy}
                className={cn(inputCls, hostLooksDashed && "border-yellow-500/60 ring-1 ring-yellow-500/30")} />
              {hostLooksDashed && (
                <p className="text-[10px] text-yellow-400 mt-1">
                  ⚠ Use dots not dashes — e.g. <code>192.168.1.249</code>
                </p>
              )}
            </Field>

            <Field label="Port" hint="RTSP default is 554">
              <input type="number" min={1} max={65535} value={form.port}
                onChange={e => set("port", parseInt(e.target.value) || 554)} disabled={busy} className={inputCls} />
            </Field>

            <Field label="Username">
              <input type="text" placeholder="admin" autoComplete="username" value={form.username}
                onChange={e => set("username", e.target.value)} disabled={busy} className={inputCls} />
            </Field>

            <Field label="Password" hint={hasExisting ? "Leave blank to keep the saved password" : undefined}>
              <div className="relative">
                <input type={showPassword ? "text" : "password"}
                  placeholder={hasExisting ? "•••••••• (unchanged)" : "Enter password"}
                  autoComplete="current-password" value={form.password}
                  onChange={e => set("password", e.target.value)} disabled={busy} className={cn(inputCls, "pr-8")} />
                <button type="button" onClick={() => setShowPassword(v => !v)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                  {showPassword ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                </button>
              </div>
            </Field>

            <Field label="Stream" hint='Hikvision: "01"=main "02"=sub · Tapo: "1" or "2"'>
              <input type="text" placeholder="01" value={form.stream}
                onChange={e => set("stream", e.target.value)} disabled={busy} className={inputCls} />
            </Field>

            <Field label="Channel" hint="Video channel number (most cameras: 1)">
              <input type="number" min={1} max={32} value={form.channel}
                onChange={e => set("channel", parseInt(e.target.value) || 1)} disabled={busy} className={inputCls} />
            </Field>

            <Field label="RTSP Transport">
              <select value={form.rtsp_transport} onChange={e => set("rtsp_transport", e.target.value)} disabled={busy} className={selectCls}>
                <option value="tcp">TCP (recommended)</option>
                <option value="udp">UDP (lower latency)</option>
              </select>
            </Field>
          </div>
        </div>
      )}

      {/* ── Section 2: Inference adapter ── */}
      <div className="rounded-lg border border-border bg-secondary/10 px-4 py-4 space-y-4">
        <p className="text-[10px] uppercase tracking-widest text-muted-foreground/60">Inference Adapter</p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="Detection Adapter" hint={selectedAdapter?.hint}>
            <select value={form.detection_adapter} onChange={e => set("detection_adapter", e.target.value)} disabled={busy} className={selectCls}>
              {ADAPTERS.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
            </select>
          </Field>

          {needsNvidia && (
            <Field label="NVIDIA Endpoint URL" hint="e.g. http://nim-host:8000/v1">
              <input type="text" placeholder="http://192.168.1.x:8000/v1" value={form.nvidia_endpoint ?? ""}
                onChange={e => set("nvidia_endpoint", e.target.value)} disabled={busy} className={inputCls} />
            </Field>
          )}

          {needsNvidia && (
            <Field label="NVIDIA API Key" hint={hasExisting ? "Leave blank to keep saved key" : "nvapi-... or bearer token"}>
              <div className="relative">
                <input type={showNvidiaKey ? "text" : "password"}
                  placeholder={hasExisting ? "•••••••• (unchanged)" : "nvapi-..."}
                  value={form.nvidia_api_key ?? ""} onChange={e => set("nvidia_api_key", e.target.value)}
                  disabled={busy} className={cn(inputCls, "pr-8")} />
                <button type="button" onClick={() => setShowNvidiaKey(v => !v)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                  {showNvidiaKey ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                </button>
              </div>
            </Field>
          )}
        </div>

        {/* Quick stop-only action */}
        {hasExisting && form.detection_adapter !== "disabled" && (
          <div className="flex items-center gap-2 pt-1">
            <button onClick={stopPipeline} disabled={busy}
              className="flex items-center gap-1.5 rounded border border-orange-500/40 bg-orange-500/10 px-3 py-1.5 text-xs font-medium text-orange-400 hover:bg-orange-500/20 disabled:opacity-50">
              {stopping ? <Loader2 className="h-3 w-3 animate-spin" /> : <Square className="h-3 w-3" />}
              {stopping ? "Stopping…" : "Stop pipeline only"}
            </button>
            <span className="text-[10px] text-muted-foreground/60">Stops inferencing without removing camera config</span>
          </div>
        )}
      </div>

      {/* Security note */}
      <p className="text-[10px] text-muted-foreground/60 border-l-2 border-border pl-2">
        Credentials are stored in <code className="text-primary">configs/camera.local.json</code>.
        Exclude this file from version control.
      </p>

      {testResult && <TestResultBadge result={testResult} />}
      {saveStatus && <StatusMsg kind={saveStatus.kind} text={saveStatus.text} />}

      {/* Action row */}
      <div className="flex items-center gap-2 flex-wrap">
        <button onClick={testConnection} disabled={busy}
          className="flex items-center gap-1.5 rounded border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground hover:border-primary/40 disabled:opacity-50 transition-colors">
          {testing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Wifi className="h-3 w-3" />}
          {testing ? "Testing…" : "Test Connection"}
        </button>

        <button onClick={save} disabled={busy}
          className="flex items-center gap-1.5 rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
          {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
          {saving ? "Saving…" : hasExisting ? "Update camera" : "Save camera"}
        </button>

        {hasExisting && (
          <button onClick={remove} disabled={busy}
            className="flex items-center gap-1.5 rounded border border-red-500/40 bg-red-500/10 px-3 py-1.5 text-xs font-medium text-red-400 hover:bg-red-500/20 disabled:opacity-50 ml-auto">
            {deleting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
            {deleting ? "Removing…" : "Delete config"}
          </button>
        )}
      </div>
    </div>
  );
}
