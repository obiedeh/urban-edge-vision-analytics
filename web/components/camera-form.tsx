import { useEffect, useMemo, useRef, useState } from "react";
import {
  api, apiErrorMessage, cameraToIn,
  type Camera, type CameraIn, type CameraProfile, type CameraTestResult, type Playback,
  type UploadRecord, type UploadSourceKind, type UsbDevice,
} from "@/lib/api";
import { StatusMsg } from "@/components/status-chip";
import { SourceKindBadge } from "@/components/source-kind-badge";
import { cn, inputCls, selectCls, btnPrimary, btnGhost } from "@/lib/utils";
import { Save, Eye, EyeOff, Wifi, WifiOff, Loader2, X, RotateCcw, RefreshCw, Upload, Film, Usb, Link2, Smartphone } from "lucide-react";

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

export function fmtBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export function describeUpload(u: UploadRecord): string {
  const parts = [u.width && u.height ? `${u.width}×${u.height}` : null, u.fps ? `${u.fps.toFixed(u.fps % 1 ? 2 : 0)} fps` : null, u.duration_s ? `${u.duration_s.toFixed(1)} s` : null, u.codec, fmtBytes(u.size_bytes)];
  return parts.filter(Boolean).join(" · ");
}

const STAGE_TEXT: Record<string, string> = {
  reachability: "Host not reachable",
  auth: "Authentication failed",
  path: "Stream path not found",
  codec: "Could not decode video",
  timeout: "Timed out",
  decode: "Decode error",
  device: "Device problem",
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

// ── USB device picker ────────────────────────────────────────────────────────

function UsbSection({ form, set, busy }: { form: CameraIn; set: <K extends keyof CameraIn>(k: K, v: CameraIn[K]) => void; busy: boolean }) {
  const [devices, setDevices] = useState<UsbDevice[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setLoading(true); setErr(null);
    try {
      const res = await api.cameras.usbDevices();
      setDevices(res.devices); setNote(res.note);
      if (!form.device && res.devices.length > 0) set("device", res.devices[0].path);
    } catch (e) { setErr(apiErrorMessage(e, "Could not list USB devices")); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const device = devices?.find((d) => d.path === form.device);
  // One entry per (format, size): cameras offer MJPG at high rates and raw YUYV only at low ones.
  const modes = useMemo(() => (device?.modes ?? []).map((m) => ({ ...m, key: `${m.pixel_format}:${m.width}x${m.height}` })), [device]);
  const modeKey = form.capture_width && form.capture_height ? `${form.capture_format || ""}:${form.capture_width}x${form.capture_height}` : "";
  const mode = modes.find((m) => m.key === modeKey) ?? modes.find((m) => m.key.endsWith(`:${form.capture_width}x${form.capture_height}`));
  const fpsChoices = mode?.fps ?? Array.from(new Set(modes.flatMap((m) => m.fps))).sort((a, b) => b - a);

  return (
    <>
      <p className="text-[10px] uppercase tracking-widest text-muted-foreground/60 flex items-center gap-2"><Usb className="h-3 w-3" /> USB camera</p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Field label="Device" className="sm:col-span-3" hint={device?.error ?? (note ?? "Devices under /dev/video* that can capture video. Metadata nodes are hidden.")}>
          <div className="flex items-center gap-2">
            <select value={form.device ?? ""} onChange={(e) => { set("device", e.target.value); set("capture_width", null); set("capture_height", null); set("capture_fps", null); set("capture_format", ""); }} disabled={busy || loading} className={selectCls}>
              {(devices ?? []).length === 0 && <option value="">{loading ? "Scanning…" : "No USB camera found"}</option>}
              {(devices ?? []).map((d) => <option key={d.path} value={d.path}>{d.name} — {d.path}{d.error ? " (unavailable)" : ""}</option>)}
            </select>
            <button type="button" onClick={load} disabled={busy || loading} className={btnGhost} title="Rescan devices">
              {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />} Rescan
            </button>
          </div>
        </Field>
        <Field label="Resolution and format" hint="Driver default when blank. MJPG usually offers the higher frame rates.">
          <select value={mode?.key ?? ""} onChange={(e) => { const m = modes.find((x) => x.key === e.target.value); set("capture_width", m?.width ?? null); set("capture_height", m?.height ?? null); set("capture_format", m?.pixel_format ?? ""); if (m && form.capture_fps && !m.fps.includes(form.capture_fps)) set("capture_fps", m.fps[0] ?? null); }} disabled={busy || !device} className={selectCls}>
            <option value="">Driver default</option>
            {modes.map((m) => <option key={m.key} value={m.key}>{m.width}×{m.height} · {m.pixel_format}{m.fps.length ? ` · up to ${m.fps[0]} fps` : ""}</option>)}
          </select>
        </Field>
        <Field label="Frame rate" hint="Rates the device offers for the chosen mode">
          <select value={form.capture_fps ?? ""} onChange={(e) => set("capture_fps", e.target.value ? parseFloat(e.target.value) : null)} disabled={busy || !device} className={selectCls}>
            <option value="">Driver default</option>
            {fpsChoices.map((f) => <option key={f} value={f}>{f} fps</option>)}
          </select>
        </Field>
        <Field label="Chosen mode" hint="Passed to the decoder as video_size, framerate and input_format">
          <div className="text-[11px] text-muted-foreground font-mono pt-1.5">{form.capture_width ? `${form.capture_width}x${form.capture_height}` : "default"}{form.capture_format ? ` ${form.capture_format}` : ""}{form.capture_fps ? ` @ ${form.capture_fps}` : ""}</div>
        </Field>
      </div>
      {err && <StatusMsg kind="err" text={err} />}
      {devices && devices.length === 0 && <StatusMsg kind="warn" text={note ?? "No USB camera found."} />}
    </>
  );
}

// ── Upload picker ────────────────────────────────────────────────────────────

function UploadSection({ form, set, busy, onUploaded }: { form: CameraIn; set: <K extends keyof CameraIn>(k: K, v: CameraIn[K]) => void; busy: boolean; onUploaded?: (u: UploadRecord) => void }) {
  const [uploads, setUploads] = useState<UploadRecord[]>([]);
  const [kind, setKind] = useState<UploadSourceKind>("recorded");
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  async function load() {
    try { setUploads(await api.cameras.uploads.list()); }
    catch (e) { setErr(apiErrorMessage(e, "Could not list uploads")); }
  }
  useEffect(() => { void load(); }, []);

  async function upload() {
    if (!file) return;
    setErr(null); setProgress(0);
    try {
      const rec = await api.cameras.uploads.upload(file, kind, setProgress);
      await load();
      set("upload_id", rec.id);
      setFile(null); if (fileRef.current) fileRef.current.value = "";
      onUploaded?.(rec);
    } catch (e) { setErr(apiErrorMessage(e, "Upload failed")); }
    finally { setProgress(null); }
  }

  const selected = uploads.find((u) => u.id === form.upload_id);
  const uploading = progress !== null;

  return (
    <>
      <p className="text-[10px] uppercase tracking-widest text-muted-foreground/60 flex items-center gap-2"><Film className="h-3 w-3" /> Uploaded video</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Field label="Video to play" className="sm:col-span-2" hint={selected ? <span className="flex items-center gap-2 flex-wrap"><SourceKindBadge kind={selected.source_kind === "generated" ? "uploaded_generated" : "uploaded_recorded"} />{describeUpload(selected)}</span> : "Pick an uploaded file, or upload a new one below."}>
          <select value={form.upload_id ?? ""} onChange={(e) => set("upload_id", e.target.value)} disabled={busy || uploading} className={selectCls}>
            <option value="">{uploads.length ? "Choose an uploaded video…" : "No uploads yet"}</option>
            {uploads.map((u) => <option key={u.id} value={u.id}>{u.filename} · {u.source_kind} · {fmtBytes(u.size_bytes)}</option>)}
          </select>
        </Field>
        <Field label="Playback">
          <select value={form.playback ?? "loop"} onChange={(e) => set("playback", e.target.value as Playback)} disabled={busy} className={selectCls}>
            <option value="loop">Loop (restart at the end)</option>
            <option value="once">Play once, then stop</option>
          </select>
        </Field>
        <Field label="Frame rate" hint="Uploads always play at the file's own frame rate.">
          <div className="text-[11px] text-muted-foreground pt-1.5">{selected?.fps ? `${selected.fps} fps (native)` : "native"}</div>
        </Field>
      </div>

      <div className="rounded border border-border bg-secondary/20 px-3 py-3 space-y-3">
        <p className="text-xs font-medium text-foreground flex items-center gap-2"><Upload className="h-3.5 w-3.5" /> Upload a new file</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="File" hint="MP4, MOV or MKV. The size limit is set on the server (default 2 GB).">
            <input ref={fileRef} type="file" accept=".mp4,.mov,.mkv,video/mp4,video/quicktime,video/x-matroska" disabled={busy || uploading} onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-xs text-muted-foreground file:mr-3 file:rounded file:border file:border-border file:bg-background file:px-2 file:py-1 file:text-xs file:text-foreground" />
          </Field>
          <Field label="What is this footage?" hint="Shown as a badge on Live, every event and every run artifact made from it.">
            <div className="flex items-center gap-4 pt-1.5 text-xs">
              <label className="inline-flex items-center gap-1.5"><input type="radio" name="upload-kind" checked={kind === "recorded"} onChange={() => setKind("recorded")} disabled={busy || uploading} /> Recorded (real camera)</label>
              <label className="inline-flex items-center gap-1.5"><input type="radio" name="upload-kind" checked={kind === "generated"} onChange={() => setKind("generated")} disabled={busy || uploading} /> Generated (simulation, AI)</label>
            </div>
          </Field>
        </div>
        <div className="flex items-center gap-3">
          <button type="button" onClick={upload} disabled={busy || uploading || !file} className={btnPrimary}>
            {uploading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Upload className="h-3 w-3" />}
            {uploading ? `Uploading ${Math.round((progress ?? 0) * 100)}%` : "Upload"}
          </button>
          {file && !uploading && <span className="text-[11px] text-muted-foreground">{file.name} · {fmtBytes(file.size)}</span>}
          {uploading && <div className="flex-1 h-1.5 rounded bg-secondary overflow-hidden"><div className="h-full bg-primary transition-all" style={{ width: `${Math.round((progress ?? 0) * 100)}%` }} /></div>}
        </div>
      </div>
      {err && <StatusMsg kind="err" text={err} />}
    </>
  );
}

// ── form ─────────────────────────────────────────────────────────────────────

interface Props {
  profiles: CameraProfile[];
  /** when set, the form edits this camera (PUT); otherwise creates (POST) */
  camera?: Camera | null;
  onSaved: (cam: Camera) => void;
  onCancel: () => void;
  /** called after a successful upload so the parent can refresh its uploads list */
  onUploaded?: (u: UploadRecord) => void;
  /** profile to preselect when creating (e.g. "uploaded_video" from the Upload video button) */
  initialProfile?: string;
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
    source_url: "",
    device: "",
    capture_width: null,
    capture_height: null,
    capture_fps: null,
    capture_format: "",
    upload_id: "",
    playback: "loop",
  };
}

export function CameraForm({ profiles, camera, onSaved, onCancel, onUploaded, initialProfile: initialProfileType }: Props) {
  const byType = useMemo(() => new Map(profiles.map((p) => [p.model_type, p])), [profiles]);
  const initialProfile = camera
    ? byType.get(camera.profile)
    : (initialProfileType ? byType.get(initialProfileType) : undefined) ?? profiles.find((p) => p.model_type === "generic_rtsp") ?? profiles[0];

  const [form, setForm] = useState<CameraIn>(() => (camera ? cameraToIn(camera) : blankForm(initialProfile)));
  /** true while stream_path tracks the profile default (auto-fill mode) */
  const [pathAuto, setPathAuto] = useState(() => !camera || camera.stream_path === "");
  const [showPassword, setShowPassword] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [test, setTest] = useState<CameraTestResult | null>(null);

  const profile = byType.get(form.profile);
  const connector = profile?.connector ?? "network";
  const needsHost = connector === "network" && (profile?.requires_host ?? true);
  const canTest = connector === "network" || connector === "rtsp_url" || connector === "usb" || connector === "upload";

  // Reset form when switching between cameras in the parent.
  useEffect(() => {
    if (!camera) return;
    setForm(cameraToIn(camera));
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
      source_url: (form.source_url ?? "").trim(),
      stream_path: pathAuto ? "" : form.stream_path.trim(),
      port: needsHost ? (form.port ?? null) : null,
    };
  }

  function validate(): string | null {
    if (!form.name.trim()) return "Name is required.";
    if (needsHost && !form.host.trim()) return `Host is required for ${profile?.label ?? "this"} cameras.`;
    if (needsHost && /^\d+(-\d+){3}$/.test(form.host.trim())) return "Host uses dashes — use dots (192.0.2.249).";
    if (connector === "rtsp_url" && !/^rtsps?:\/\//i.test((form.source_url ?? "").trim())) return "Paste a link that starts with rtsp:// or rtsps://.";
    if (connector === "usb" && !form.device) return "Choose a USB camera device.";
    if (connector === "upload" && !form.upload_id) return "Choose or upload a video to play.";
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
  const linkHasCreds = /^rtsps?:\/\/[^/@\s]+@/i.test((form.source_url ?? "").trim());

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-foreground">{camera ? `Edit camera: ${camera.name}` : connector === "upload" ? "Upload a video and play it as a camera" : "Add camera"}</h2>
        <button type="button" onClick={onCancel} className="text-muted-foreground hover:text-foreground"><X className="h-4 w-4" /></button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Field label="Name">
          <input type="text" value={form.name} onChange={(e) => set("name", e.target.value)} disabled={busy} placeholder="North approach" className={inputCls} />
        </Field>
        <Field label="Profile" hint={profile?.notes || undefined}>
          <select value={form.profile} onChange={(e) => changeProfile(e.target.value)} disabled={busy} className={selectCls}>
            <optgroup label="Network cameras (host + path)">
              {profiles.filter((p) => p.connector === "network").map((p) => <option key={p.model_type} value={p.model_type}>{p.label}</option>)}
            </optgroup>
            <optgroup label="Other video feeds">
              {profiles.filter((p) => p.connector !== "network").map((p) => <option key={p.model_type} value={p.model_type}>{p.label}</option>)}
            </optgroup>
          </select>
        </Field>
      </div>

      {connector === "rtsp_url" && (
        <>
          <p className="text-[10px] uppercase tracking-widest text-muted-foreground/60 flex items-center gap-2"><Link2 className="h-3 w-3" /> RTSP link</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field
              label="Stream link"
              className="sm:col-span-2"
              hint={linkHasCreds
                ? "This link contains a username and password. They will be taken out of the link, stored encrypted like any camera password, and never shown or logged."
                : "Full rtsp:// or rtsps:// address, for example rtsp://192.0.2.50:554/stream1. Credentials can stay in the link or go in the fields below."}
            >
              <input type="text" autoComplete="off" spellCheck={false} value={form.source_url ?? ""} onChange={(e) => set("source_url", e.target.value)} disabled={busy} placeholder="rtsp://192.0.2.50:554/stream1" className={cn(inputCls, "font-mono")} />
            </Field>
            <Field label="Username" hint="Optional. Overrides a username inside the link.">
              <input type="text" autoComplete="username" value={form.username} onChange={(e) => set("username", e.target.value)} disabled={busy} placeholder="viewer" className={inputCls} />
            </Field>
            <Field label="Password" hint={camera?.has_password ? "Leave blank to keep the stored password" : "Optional. Overrides a password inside the link."}>
              <div className="relative">
                <input type={showPassword ? "text" : "password"} autoComplete="new-password" value={form.password} onChange={(e) => set("password", e.target.value)} disabled={busy} placeholder={camera?.has_password ? "(unchanged)" : "Enter password"} className={cn(inputCls, "pr-8")} />
                <button type="button" onClick={() => setShowPassword((v) => !v)} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" aria-label="toggle password visibility">
                  {showPassword ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                </button>
              </div>
            </Field>
            <Field label="RTSP transport">
              <select value={form.rtsp_transport} onChange={(e) => set("rtsp_transport", e.target.value as "tcp" | "udp")} disabled={busy} className={selectCls}>
                <option value="tcp">TCP (recommended)</option>
                <option value="udp">UDP (lower latency)</option>
              </select>
            </Field>
          </div>
        </>
      )}

      {connector === "usb" && <UsbSection form={form} set={set} busy={busy} />}
      {connector === "upload" && <UploadSection form={form} set={set} busy={busy} onUploaded={onUploaded} />}

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

      {connector === "browser" && profile && (
        <div className="text-[11px] text-muted-foreground/80 rounded border border-border bg-secondary/20 px-3 py-2 space-y-1">
          <p className="flex items-center gap-2 text-foreground"><Smartphone className="h-3.5 w-3.5" /> {profile.label}: no host or credentials.</p>
          <p>Open the Live page in the browser whose camera you want to share and press <b>Share camera</b>. On a laptop you pick the camera from a list; on a phone you choose front or back.</p>
          <p>Browsers only allow camera access on <code>localhost</code> or over HTTPS. For a phone or another computer on the LAN, enable the optional HTTPS front door (README: <i>Browser camera from another device</i>).</p>
        </div>
      )}

      {connector === "synthetic" && profile && (
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
        {canTest && (
          <button type="button" onClick={runTest} disabled={busy} className={btnGhost}>
            {testing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Wifi className="h-3 w-3" />}
            {testing ? "Testing…" : connector === "upload" ? "Check file" : "Test connection"}
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
