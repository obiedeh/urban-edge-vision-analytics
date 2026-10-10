import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, apiErrorMessage, cameraToIn, type Camera, type CameraProfile, type CameraTestResult, type UploadRecord } from "@/lib/api";
import { CameraForm, TestResultCard, describeUpload } from "@/components/camera-form";
import { CameraStateChip, ProfileChip, StatusMsg } from "@/components/status-chip";
import { SourceKindBadge } from "@/components/source-kind-badge";
import { cn, btnGhost, btnPrimary, btnDanger, formatSeconds } from "@/lib/utils";
import { PlusCircle, Pencil, Trash2, Wifi, Loader2, Eye, EyeOff, Power, Video, RotateCcw, Film, ChevronDown, ChevronRight, Upload } from "lucide-react";

function Switch({ checked, onChange, disabled, title }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; title?: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      title={title}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn("relative h-5 w-9 rounded-full border transition-colors disabled:opacity-50", checked ? "bg-primary/80 border-primary" : "bg-secondary border-border")}
    >
      <span className={cn("absolute top-0.5 h-3.5 w-3.5 rounded-full bg-white transition-all", checked ? "left-[18px]" : "left-0.5")} />
    </button>
  );
}

function CameraCard({
  camera, onEdit, onChanged, onDeleted,
}: {
  camera: Camera;
  onEdit: () => void;
  onChanged: (cam: Camera) => void;
  onDeleted: () => void;
}) {
  const [busy, setBusy] = useState<"" | "enable" | "live" | "test" | "delete" | "restart">("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [test, setTest] = useState<CameraTestResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const rt = camera.runtime;

  async function toggleEnabled(v: boolean) {
    setBusy("enable"); setErr(null);
    try { onChanged(await api.cameras.setEnabled(camera.id, v)); }
    catch (e) { setErr(apiErrorMessage(e)); }
    finally { setBusy(""); }
  }

  async function toggleLive(v: boolean) {
    setBusy("live"); setErr(null);
    try {
      onChanged(await api.cameras.update(camera.id, { ...cameraToIn(camera), show_on_live: v }));
    } catch (e) { setErr(apiErrorMessage(e)); }
    finally { setBusy(""); }
  }

  async function restart() {
    setBusy("restart"); setErr(null);
    try { onChanged(await api.cameras.restart(camera.id)); }
    catch (e) { setErr(apiErrorMessage(e, "Restart failed")); }
    finally { setBusy(""); }
  }

  async function runTest() {
    setBusy("test"); setErr(null); setTest(null);
    try { setTest(await api.cameras.testSaved(camera.id)); }
    catch (e) { setErr(apiErrorMessage(e, "Test failed")); }
    finally { setBusy(""); }
  }

  async function remove() {
    setBusy("delete"); setErr(null);
    try { await api.cameras.remove(camera.id); onDeleted(); }
    catch (e) { setErr(apiErrorMessage(e, "Delete failed")); setBusy(""); }
  }

  return (
    <div className={cn("rounded-lg border bg-card p-4 space-y-3", camera.enabled ? "border-border" : "border-border/60 opacity-80")}>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <Link to={`/live/${encodeURIComponent(camera.id)}`} className="text-sm font-semibold text-foreground hover:text-primary">{camera.name}</Link>
            <ProfileChip profile={camera.profile} />
            <SourceKindBadge kind={camera.source_kind} />
            <CameraStateChip state={camera.enabled ? rt?.state ?? null : "stopped"} />
            {!camera.enabled && <span className="text-[10px] text-muted-foreground">disabled</span>}
          </div>
          <div className="text-[10px] font-mono text-muted-foreground/70 break-all">
            id {camera.id}
            {camera.masked_url ? ` · ${camera.masked_url}` : ""}
            {camera.connector === "usb" ? ` · ${camera.device}${camera.capture_width ? ` ${camera.capture_width}×${camera.capture_height}` : ""}${camera.capture_format ? ` ${camera.capture_format}` : ""}${camera.capture_fps ? ` @ ${camera.capture_fps}` : ""}` : ""}
            {camera.connector === "upload" && camera.upload ? ` · ${camera.upload.filename} · ${camera.playback === "once" ? "play once" : "loop"}` : ""}
            {camera.connector === "upload" && !camera.upload ? " · upload missing" : ""}
          </div>
          <div className="flex items-center gap-3 flex-wrap text-[11px] text-muted-foreground tabular-nums">
            {rt && camera.enabled ? (
              <>
                <span>fps <b className="text-foreground font-medium">{rt.fps.toFixed(1)}</b></span>
                {rt.source_width && <span>{rt.source_width}×{rt.source_height}{rt.source_fps ? ` @ ${rt.source_fps.toFixed(0)}` : ""}</span>}
                {rt.codec && <span className="font-mono">{rt.codec}</span>}
                <span>dropped {rt.frames_dropped}</span>
                {camera.connector === "upload" ? <span>loops {rt.loops}</span> : <span>reconnects {rt.reconnects}</span>}
                {rt.uptime_s != null && <span>up {formatSeconds(rt.uptime_s)}</span>}
                {rt.last_frame_age_s != null && <span>last frame {formatSeconds(rt.last_frame_age_s)} ago</span>}
              </>
            ) : (
              <span>not running</span>
            )}
          </div>
          {rt?.last_error && camera.enabled && (
            <div className="text-[11px] text-red-400 break-words">{rt.last_error}</div>
          )}
        </div>

        <div className="flex items-center gap-4 flex-wrap shrink-0">
          <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Power className="h-3 w-3" /> Enabled
            <Switch checked={camera.enabled} onChange={toggleEnabled} disabled={busy !== ""} title="Decode and run inference" />
          </label>
          <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            {camera.show_on_live ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />} Show on Live
            <Switch checked={camera.show_on_live} onChange={toggleLive} disabled={busy !== ""} />
          </label>
        </div>
      </div>

      {test && <TestResultCard result={test} onClose={() => setTest(null)} />}
      {err && <StatusMsg kind="err" text={err} />}

      <div className="flex items-center gap-2 flex-wrap">
        {camera.profile !== "synthetic" && camera.profile !== "browser_webrtc" && (
          <button onClick={runTest} disabled={busy !== ""} className={btnGhost}>
            {busy === "test" ? <Loader2 className="h-3 w-3 animate-spin" /> : <Wifi className="h-3 w-3" />} Test
          </button>
        )}
        {camera.enabled && (camera.connector === "upload" || rt?.state === "error" || rt?.state === "ended") && (
          <button onClick={restart} disabled={busy !== ""} className={btnGhost} title={camera.connector === "upload" ? "Play the video again from the start" : "Reconnect now"}>
            {busy === "restart" ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />} {camera.connector === "upload" ? "Replay" : "Reconnect"}
          </button>
        )}
        <button onClick={onEdit} disabled={busy !== ""} className={btnGhost}><Pencil className="h-3 w-3" /> Edit</button>
        <Link to={`/studio?camera_id=${encodeURIComponent(camera.id)}`} className={btnGhost}>Studio</Link>
        <div className="ml-auto flex items-center gap-2">
          {confirmDelete ? (
            <>
              <span className="text-[11px] text-red-300">Delete "{camera.name}" and its bindings/zones?</span>
              <button onClick={remove} disabled={busy !== ""} className={btnDanger}>
                {busy === "delete" ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />} Confirm delete
              </button>
              <button onClick={() => setConfirmDelete(false)} disabled={busy !== ""} className="text-[11px] text-muted-foreground hover:text-foreground">Cancel</button>
            </>
          ) : (
            <button onClick={() => setConfirmDelete(true)} disabled={busy !== ""} className={cn(btnGhost, "text-red-400/80 hover:text-red-400 hover:border-red-500/40")}>
              <Trash2 className="h-3 w-3" /> Delete
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function UploadsSection({ uploads, cameras, onChanged, onUpload }: { uploads: UploadRecord[]; cameras: Camera[]; onChanged: () => void; onUpload: () => void }) {
  const [open, setOpen] = useState(true);
  const [busy, setBusy] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);
  const names = new Map(cameras.map((c) => [c.id, c.name]));

  async function remove(u: UploadRecord) {
    setBusy(u.id); setErr(null);
    try { await api.cameras.uploads.remove(u.id); onChanged(); }
    catch (e) { setErr(apiErrorMessage(e, "Delete failed")); }
    finally { setBusy(""); }
  }

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex w-full items-center gap-2 px-4 py-2.5 text-xs font-medium text-muted-foreground">
        <button onClick={() => setOpen((v) => !v)} className="flex items-center gap-2 hover:text-foreground">
          {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          <Film className="h-3.5 w-3.5" /> Uploaded videos
          <span className="text-[10px] font-normal">{uploads.length} file{uploads.length === 1 ? "" : "s"} · stored next to the database, outside the repository · delete removes the file</span>
        </button>
        <button onClick={onUpload} className={cn(btnGhost, "ml-auto")}><Upload className="h-3 w-3" /> Upload video</button>
      </div>
      {open && (
        <div className="border-t border-border divide-y divide-border">
          {uploads.length === 0 && (
            <p className="px-4 py-3 text-xs text-muted-foreground">
              No uploads yet. Click <button onClick={onUpload} className="text-primary underline underline-offset-2 font-medium">Upload video</button> to add an MP4, MOV or MKV and play it as a camera.
            </p>
          )}
          {uploads.map((u) => (
            <div key={u.id} className="flex items-center gap-3 px-4 py-2 text-xs flex-wrap">
              <SourceKindBadge kind={u.source_kind === "generated" ? "uploaded_generated" : "uploaded_recorded"} />
              <span className="font-medium text-foreground">{u.filename}</span>
              <span className="text-muted-foreground tabular-nums">{describeUpload(u)}</span>
              <span className="text-[10px] text-muted-foreground/70 ml-auto">
                {u.camera_ids.length ? `used by ${u.camera_ids.map((id) => names.get(id) ?? id).join(", ")}` : "not used"}
              </span>
              <button
                onClick={() => remove(u)}
                disabled={busy !== "" || u.camera_ids.length > 0}
                title={u.camera_ids.length ? "Delete or re-point the cameras using this file first" : "Delete the file"}
                className={cn(btnGhost, "text-red-400/80 hover:text-red-400 hover:border-red-500/40")}
              >
                {busy === u.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />} Delete
              </button>
            </div>
          ))}
          {err && <div className="px-4 py-2"><StatusMsg kind="err" text={err} /></div>}
        </div>
      )}
    </div>
  );
}

export function CamerasPage() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [uploads, setUploads] = useState<UploadRecord[]>([]);
  const [profiles, setProfiles] = useState<CameraProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  /** null = closed, "new" = add camera, "upload" = add camera with the Uploaded video profile preselected */
  const [editing, setEditing] = useState<Camera | null | "new" | "upload">(null);
  const [searchParams, setSearchParams] = useSearchParams();

  // /cameras?action=upload (linked from Live) opens the upload form directly.
  useEffect(() => {
    if (searchParams.get("action") === "upload") {
      setEditing("upload");
      const next = new URLSearchParams(searchParams);
      next.delete("action");
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  async function reload() {
    try {
      const [cams, ups] = await Promise.all([api.cameras.list(), api.cameras.uploads.list().catch(() => [] as UploadRecord[])]);
      setCameras(cams);
      setUploads(ups);
      setError(null);
    } catch (e) { setError(apiErrorMessage(e, "Could not load cameras")); }
  }

  useEffect(() => {
    let dead = false;
    Promise.all([api.cameras.list(), api.cameras.profiles(), api.cameras.uploads.list().catch(() => [] as UploadRecord[])])
      .then(([cams, profs, ups]) => { if (!dead) { setCameras(cams); setProfiles(profs); setUploads(ups); } })
      .catch((e) => { if (!dead) setError(apiErrorMessage(e, "Could not load cameras")); })
      .finally(() => { if (!dead) setLoading(false); });
    const t = setInterval(() => { void reload(); }, 3000);
    return () => { dead = true; clearInterval(t); };
  }, []);

  function upsert(cam: Camera) {
    setCameras((prev) => (prev.some((c) => c.id === cam.id) ? prev.map((c) => (c.id === cam.id ? cam : c)) : [...prev, cam]));
  }

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <Video className="h-4 w-4 text-muted-foreground" />
          <h1 className="text-lg font-semibold">Cameras</h1>
          <span className="text-xs text-muted-foreground">{cameras.length} configured · {cameras.filter((c) => c.runtime?.state === "streaming").length} streaming</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setEditing(editing === "upload" ? null : "upload")}
            className={cn(btnPrimary, editing === "upload" && "bg-primary/70")}
            title="Upload an MP4, MOV or MKV and play it as a camera"
          >
            <Upload className="h-3.5 w-3.5" /> Upload video
          </button>
          <button
            onClick={() => setEditing(editing === "new" ? null : "new")}
            className={cn(btnPrimary, editing === "new" && "bg-primary/70")}
          >
            <PlusCircle className="h-3.5 w-3.5" /> Add camera
          </button>
        </div>
      </div>

      {error && <StatusMsg kind="err" text={error} />}

      {editing !== null && profiles.length > 0 && (
        <div className="rounded-lg border border-primary/40 bg-card px-5 py-5">
          <CameraForm
            key={editing === "new" || editing === "upload" ? editing : editing.id}
            profiles={profiles}
            camera={editing === "new" || editing === "upload" ? null : editing}
            initialProfile={editing === "upload" ? "uploaded_video" : undefined}
            openFilePicker={editing === "upload"}
            onSaved={(cam) => { upsert(cam); setEditing(null); void reload(); }}
            onCancel={() => setEditing(null)}
            onUploaded={() => { void reload(); }}
          />
        </div>
      )}

      {loading && <div className="space-y-3">{[...Array(2)].map((_, i) => <div key={i} className="h-28 rounded-lg snapshot-shimmer" />)}</div>}

      {!loading && cameras.length === 0 && editing === null && (
        <div className="rounded-lg border border-dashed border-border bg-card/50 px-4 py-10 text-center text-sm text-muted-foreground space-y-4">
          <p>No cameras yet. Pick a vendor profile, paste an RTSP link, choose a USB camera, upload a video, or share your browser's camera. Use the <b>Synthetic test feed</b> profile for a demo without hardware.</p>
          <div className="flex items-center justify-center gap-3 flex-wrap">
            <button onClick={() => setEditing("upload")} className={btnPrimary}><Upload className="h-3.5 w-3.5" /> Upload video</button>
            <button onClick={() => setEditing("new")} className={btnGhost}><PlusCircle className="h-3.5 w-3.5" /> Add camera</button>
          </div>
        </div>
      )}

      <div className="space-y-3">
        {cameras.map((cam) => (
          <CameraCard
            key={cam.id}
            camera={cam}
            onEdit={() => setEditing(cam)}
            onChanged={upsert}
            onDeleted={() => { setCameras((prev) => prev.filter((c) => c.id !== cam.id)); if (typeof editing === "object" && editing?.id === cam.id) setEditing(null); void reload(); }}
          />
        ))}
      </div>

      {!loading && (
        <UploadsSection uploads={uploads} cameras={cameras} onChanged={() => { void reload(); }} onUpload={() => setEditing("upload")} />
      )}
    </div>
  );
}
