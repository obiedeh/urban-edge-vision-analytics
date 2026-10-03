import { useEffect, useMemo, useState } from "react";
import {
  api, apiErrorMessage,
  type Camera, type CameraIn, type CameraProfile, type CameraTestResult,
} from "@/lib/api";
import { StatusMsg } from "@/components/status-chip";
import { cn, inputCls, selectCls, btnPrimary, btnGhost } from "@/lib/utils";
import { Save, Eye, EyeOff, Wifi, WifiOff, Loader2, X, RotateCcw } from "lucide-react";

// ── helpers ──────────────────────────────────────────────────────────────────

function Field({ label, hint, children, className }: { label: string; hint?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("space-y-1", className)}>
      <label className="block text-xs font-medium text-muted-foreground">{label}</label>
      {children}
      {hint && <p className="text-[10px] text-muted-foreground/60 break-words">{hint}</p>}
    </div>
  );
}

function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <label className={cn("inline-flex items-center gap-2 text-xs text-foreground cursor-pointer select-none", disabled && "opacity-50")}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn("relative h-5 w-9 rounded-full border transition-colors", checked ? "bg-primary/80 border-primary" : "bg-secondary border-border")}
      >
        <span className={cn("absolute top-0.5 h-3.5 w-3.5 rounded-full bg-white transition-all", checked ? "left-[18px]" : "left-0.5")} />
      </button>
      {label}
    </label>
  );
}

/** Fill the profile's path template for quality/channel (mirrors CameraProfile.stream_path). */
export function profilePath(profile: CameraProfile | undefined, quality: "main" | "sub", channel: number): string {
  if (!profile) return "";
  const tpl = quality === "sub" ? profile.sub_path : profile.main_path;
  return tpl.split("{channel}").join(String(channel)).split("{channel2}").join(String(channel).padStart(2, "0"));
}

const STAGE_TEXT: Record<string, string> = {
  reachability: "Host not reachable",
  auth: "Authentication failed",
  path: "Stream path not found",
  codec: "Could not decode video",
  timeout: "Timed out",
  decode: "Decode error",
  url: "Invalid camera URL",
};

export function TestResultCard({ result, onClose }: { result: CameraTestResult; onClose?: () => void }) {
  if (result.ok) {
    return (
      <div className="flex items-start gap-3 rounded border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
        {result.thumbnail_data_url ? (
          <img src={result.thumbnail_data_url} alt="probe thumbnail" className="h-20 w-auto rounded border border-emerald-500/30 shrink-0" />
        ) : (
          <Wifi className="h-4 w-4 mt-0.5 shrink-0" />
        )}
        <div className="min-w-0 flex-1 space-y-0.5">
          <div className="font-semibold">Stream OK{result.note ? ` — ${result.note}` : ""}</div>
          {(result.width || result.codec || result.fps || result.open_ms) && (
            <div className="font-mono text-[10px] text-emerald-300/80 flex flex-wrap gap-3">
              {result.width && <span>{result.width}×{result.height}</span>}
              {result.codec && <span>{result.codec}</span>}
              {result.fps != null && <span>{result.fps.toFixed(1)} fps</span>}
              {result.open_ms != null && <span>open {result.open_ms.toFixed(0)} ms</span>}
            </div>
          )}
          {result.masked_url && <div className="font-mono text-[10px] text-emerald-300/60 break-all">{result.masked_url}</div>}
        </div>
        {onClose && <button type="button" onClick={onClose} className="shrink-0 text-emerald-300/60 hover:text-emerald-200"><X className="h-3.5 w-3.5" /></button>}
      </div>
    );
  }
  return (
    <div className="flex items-start gap-2 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
      <WifiOff className="h-4 w-4 mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="font-semibold">
          {STAGE_TEXT[result.stage] ?? "Test failed"}{" "}
          <span className="font-mono text-[10px] font-normal text-red-300/60">stage: {result.stage}</span>
        </div>
        {result.error && <div className="text-[11px] text-red-300/90 break-words">{result.error}</div>}
        {result.masked_url && <div className="font-mono text-[10px] text-red-300/60 break-all">{result.masked_url}</div>}
      </div>
      {onClose && <button type="button" onClick={onClose} className="shrink-0 text-red-300/60 hover:text-red-200"><X className="h-3.5 w-3.5" /></button>}
    </div>
  );
}

// ── form ─────────────────────────────────────────────────────────────────────

interface Props {
  profiles: CameraProfile[];
  /** when set, the form edits this camera (PUT); otherwise creates (POST) */
  camera?: Camera | null;
  onSaved: (cam: Camera) => void;
  onCancel: () => void;
}

function blankForm(profile: CameraProfile | undefined): CameraIn {
  return {
    name: "",
    profile: profile?.model_type ?? "generic_rtsp",
    host: "",
    port: profile?.default_port || null,
    username: "",
    password: "",
    stream_path: "",
    stream_quality: "main",
    channel: 1,
    rtsp_transport: "tcp",
    enabled: true,
    show_on_live: true,
  };
}

export function CameraForm({ profiles, camera, onSaved, onCancel }: Props) {
  const byType = useMemo(() => new Map(profiles.map((p) => [p.model_type, p])), [profiles]);
  const initialProfile = camera ? byType.get(camera.profile) : profiles.find((p) => p.model_type === "generic_rtsp") ?? profiles[0];

  const [form, setForm] = useState<CameraIn>(() =>
    camera
      ? {
          name: camera.name,
          profile: camera.profile,
          host: camera.host,
          port: camera.port,
          username: camera.username,
          password: "",
          stream_path: camera.stream_path,
          stream_quality: camera.stream_quality,
          channel: camera.channel,
          rtsp_transport: camera.rtsp_transport,
          enabled: camera.enabled,
          show_on_live: camera.show_on_live,
        }
      : blankForm(initialProfile)
  );
  /** true while stream_path tracks the profile default (auto-fill mode) */
  const [pathAuto, setPathAuto] = useState(() => !camera || camera.stream_path === "");
  const [showPassword, setShowPassword] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [test, setTest] = useState<CameraTestResult | null>(null);

  const profile = byType.get(form.profile);
  const needsHost = profile?.requires_host ?? true;

  // Reset form when switching between cameras in the parent.
  useEffect(() => {
    if (!camera) return;
    setForm({
      name: camera.name, profile: camera.profile, host: camera.host, port: camera.port, username: camera.username,
      password: "", stream_path: camera.stream_path, stream_quality: camera.stream_quality, channel: camera.channel,
      rtsp_transport: camera.rtsp_transport, enabled: camera.enabled, show_on_live: camera.show_on_live,
    });
    setPathAuto(camera.stream_path === "");
    setTest(null); setError(null);
  }, [camera]);

  function set<K extends keyof CameraIn>(key: K, value: CameraIn[K]) {
    setForm((p) => ({ ...p, [key]: value }));
    setError(null);
    setTest(null);
  }

  function changeProfile(modelType: string) {
    const p = byType.get(modelType);
    setForm((prev) => ({
      ...prev,
      profile: modelType,
      port: p?.requires_host ? (p.default_port || null) : null,
      // auto-fill mode: the server derives the path from the profile when stream_path is ""
      stream_path: pathAuto ? "" : prev.stream_path,
    }));
    setError(null); setTest(null);
  }

  const displayedPath = pathAuto ? profilePath(profile, form.stream_quality, form.channel) : form.stream_path;

  /** Build the payload: an empty stream_path means "use the profile default". */
  function payload(): CameraIn {
    return {
      ...form,
      name: form.name.trim(),
      host: form.host.trim(),
      stream_path: pathAuto ? "" : form.stream_path.trim(),
      port: needsHost ? (form.port ?? null) : null,
    };
  }

  function validate(): string | null {
    if (!form.name.trim()) return "Name is required.";
    if (needsHost && !form.host.trim()) return `Host is required for ${profile?.label ?? "this"} cameras.`;
    if (needsHost && /^\d+(-\d+){3}$/.test(form.host.trim())) return "Host uses dashes — use dots (192.0.2.249).";
    return null;
  }

  async function runTest() {
    const v = validate();
    if (v) { setError(v); return; }
    setTesting(true); setTest(null); setError(null);
    try {
      // On edit with the password left blank the server uses the stored (encrypted)
      // password for this camera_id, so unsaved host/path edits are still probed.
      const body = { ...payload(), password: form.password, camera_id: camera?.id };
      setTest(await api.cameras.testUnsaved(body));
    } catch (e) {
      setError(apiErrorMessage(e, "Test failed"));
    } finally { setTesting(false); }
  }

  async function save() {
    const v = validate();
    if (v) { setError(v); return; }
    setSaving(true); setError(null);
    try {
      const saved = camera
        ? await api.cameras.update(camera.id, payload())
        : await api.cameras.create(payload());
      onSaved(saved);
    } catch (e) {
      setError(apiErrorMessage(e, "Save failed"));
    } finally { setSaving(false); }
  }

  const busy = saving || testing;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-foreground">{camera ? `Edit camera: ${camera.name}` : "Add camera"}</h2>
        <button type="button" onClick={onCancel} className="text-muted-foreground hover:text-foreground"><X className="h-4 w-4" /></button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Field label="Name">
          <input type="text" value={form.name} onChange={(e) => set("name", e.target.value)} disabled={busy} placeholder="North approach" className={inputCls} />
        </Field>
        <Field label="Profile" hint={profile?.notes || undefined}>
          <select value={form.profile} onChange={(e) => changeProfile(e.target.value)} disabled={busy} className={selectCls}>
            {profiles.map((p) => <option key={p.model_type} value={p.model_type}>{p.label}</option>)}
          </select>
        </Field>
      </div>

      {needsHost && (
        <>
          <p className="text-[10px] uppercase tracking-widest text-muted-foreground/60">Connection</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Host" hint="IP address or hostname on your network">
              <input type="text" value={form.host} onChange={(e) => set("host", e.target.value)} disabled={busy} placeholder="192.0.2.50" className={inputCls} />
            </Field>
            <Field label="Port" hint={profile ? `${profile.protocol.toUpperCase()} default ${profile.default_port}` : undefined}>
              <input type="number" min={1} max={65535} value={form.port ?? ""} onChange={(e) => set("port", e.target.value ? parseInt(e.target.value) : null)} disabled={busy} className={inputCls} />
            </Field>
            <Field label="Username" hint={profile && !profile.requires_auth ? "Optional for this profile" : undefined}>
              <input type="text" autoComplete="username" value={form.username} onChange={(e) => set("username", e.target.value)} disabled={busy} placeholder="admin" className={inputCls} />
            </Field>
            <Field label="Password" hint={camera?.has_password ? "Leave blank to keep the stored password" : undefined}>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  value={form.password}
                  onChange={(e) => set("password", e.target.value)}
                  disabled={busy}
                  placeholder={camera?.has_password ? "(unchanged)" : "Enter password"}
                  className={cn(inputCls, "pr-8")}
                />
                <button type="button" onClick={() => setShowPassword((v) => !v)} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" aria-label="toggle password visibility">
                  {showPassword ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                </button>
              </div>
            </Field>
            <Field label="Stream quality" hint={profile ? <>main: <code>{profile.example_main_path}</code> · sub: <code>{profile.example_sub_path}</code></> : undefined}>
              <select value={form.stream_quality} onChange={(e) => set("stream_quality", e.target.value as "main" | "sub")} disabled={busy} className={selectCls}>
                <option value="main">Main (full resolution)</option>
                <option value="sub">Sub (low bandwidth)</option>
              </select>
            </Field>
            <Field label="Channel" hint="Most cameras: 1. NVRs: per-camera channel number.">
              <input type="number" min={1} max={64} value={form.channel} onChange={(e) => set("channel", Math.max(1, parseInt(e.target.value) || 1))} disabled={busy} className={inputCls} />
            </Field>
            <Field
              label="Stream path"
              className="sm:col-span-2"
              hint={
                <span className="flex items-center gap-2 flex-wrap">
                  {pathAuto ? "Auto-filled from the profile for the chosen quality/channel. Edit to override." : "Custom path — overrides the profile."}
                  {!pathAuto && (
                    <button type="button" onClick={() => { setPathAuto(true); set("stream_path", ""); }} className="inline-flex items-center gap-1 text-primary hover:underline">
                      <RotateCcw className="h-3 w-3" /> Reset to profile default
                    </button>
                  )}
                </span>
              }
            >
              <input
                type="text"
                value={displayedPath}
                onChange={(e) => { setPathAuto(false); set("stream_path", e.target.value); }}
                disabled={busy}
                className={cn(inputCls, "font-mono", pathAuto && "text-muted-foreground")}
              />
            </Field>
            {profile?.protocol === "rtsp" && (
              <Field label="RTSP transport">
                <select value={form.rtsp_transport} onChange={(e) => set("rtsp_transport", e.target.value as "tcp" | "udp")} disabled={busy} className={selectCls}>
                  <option value="tcp">TCP (recommended)</option>
                  <option value="udp">UDP (lower latency)</option>
                </select>
              </Field>
            )}
          </div>
        </>
      )}

      {!needsHost && profile && (
        <p className="text-[11px] text-muted-foreground/80 rounded border border-border bg-secondary/20 px-3 py-2">
          {profile.label}: no host or credentials. {profile.notes}
        </p>
      )}

      <div className="flex items-center gap-6 flex-wrap">
        <Toggle checked={form.enabled} onChange={(v) => set("enabled", v)} label="Enabled (decode and run inference)" disabled={busy} />
        <Toggle checked={form.show_on_live} onChange={(v) => set("show_on_live", v)} label="Show on Live" disabled={busy} />
      </div>

      {test && <TestResultCard result={test} onClose={() => setTest(null)} />}
      {error && <StatusMsg kind={test?.ok || !test ? "err" : "warn"} text={error} />}

      <div className="flex items-center gap-2 flex-wrap">
        {needsHost && (
          <button type="button" onClick={runTest} disabled={busy} className={btnGhost}>
            {testing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Wifi className="h-3 w-3" />}
            {testing ? "Testing…" : "Test connection"}
          </button>
        )}
        <button type="button" onClick={save} disabled={busy} className={btnPrimary}>
          {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
          {saving ? "Saving…" : camera ? "Save changes" : "Add camera"}
        </button>
        <button type="button" onClick={onCancel} disabled={busy} className="text-xs text-muted-foreground hover:text-foreground ml-auto">Cancel</button>
      </div>
    </div>
  );
}
