import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, apiErrorMessage, type Camera, type CameraProfile, type CameraTestResult } from "@/lib/api";
import { CameraForm, TestResultCard } from "@/components/camera-form";
import { CameraStateChip, ProfileChip, StatusMsg } from "@/components/status-chip";
import { cn, btnGhost, btnPrimary, btnDanger, formatSeconds } from "@/lib/utils";
import { PlusCircle, Pencil, Trash2, Wifi, Loader2, Eye, EyeOff, Power, Video } from "lucide-react";

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
  const [busy, setBusy] = useState<"" | "enable" | "live" | "test" | "delete">("");
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
      onChanged(await api.cameras.update(camera.id, {
        name: camera.name, profile: camera.profile, host: camera.host, port: camera.port, username: camera.username,
        password: "", stream_path: camera.stream_path, stream_quality: camera.stream_quality, channel: camera.channel,
        rtsp_transport: camera.rtsp_transport, enabled: camera.enabled, show_on_live: v,
      }));
    } catch (e) { setErr(apiErrorMessage(e)); }
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
            <CameraStateChip state={camera.enabled ? rt?.state ?? null : "stopped"} />
            {!camera.enabled && <span className="text-[10px] text-muted-foreground">disabled</span>}
          </div>
          <div className="text-[10px] font-mono text-muted-foreground/70 break-all">
            id {camera.id}{camera.masked_url ? ` · ${camera.masked_url}` : ""}
          </div>
          <div className="flex items-center gap-3 flex-wrap text-[11px] text-muted-foreground tabular-nums">
            {rt && camera.enabled ? (
              <>
                <span>fps <b className="text-foreground font-medium">{rt.fps.toFixed(1)}</b></span>
                {rt.source_width && <span>{rt.source_width}×{rt.source_height}{rt.source_fps ? ` @ ${rt.source_fps.toFixed(0)}` : ""}</span>}
                {rt.codec && <span className="font-mono">{rt.codec}</span>}
                <span>dropped {rt.frames_dropped}</span>
                <span>reconnects {rt.reconnects}</span>
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

export function CamerasPage() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [profiles, setProfiles] = useState<CameraProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Camera | null | "new">(null);

  async function reload() {
    try {
      const cams = await api.cameras.list();
      setCameras(cams);
      setError(null);
    } catch (e) { setError(apiErrorMessage(e, "Could not load cameras")); }
  }

  useEffect(() => {
    let dead = false;
    Promise.all([api.cameras.list(), api.cameras.profiles()])
      .then(([cams, profs]) => { if (!dead) { setCameras(cams); setProfiles(profs); } })
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
        <button
          onClick={() => setEditing(editing === "new" ? null : "new")}
          className={cn(btnPrimary, editing === "new" && "bg-primary/70")}
        >
          <PlusCircle className="h-3.5 w-3.5" /> Add camera
        </button>
      </div>

      {error && <StatusMsg kind="err" text={error} />}

      {editing !== null && profiles.length > 0 && (
        <div className="rounded-lg border border-primary/40 bg-card px-5 py-5">
          <CameraForm
            profiles={profiles}
            camera={editing === "new" ? null : editing}
            onSaved={(cam) => { upsert(cam); setEditing(null); void reload(); }}
            onCancel={() => setEditing(null)}
          />
        </div>
      )}

      {loading && <div className="space-y-3">{[...Array(2)].map((_, i) => <div key={i} className="h-28 rounded-lg snapshot-shimmer" />)}</div>}

      {!loading && cameras.length === 0 && editing === null && (
        <div className="rounded-lg border border-dashed border-border bg-card/50 px-4 py-10 text-center text-sm text-muted-foreground">
          No cameras yet. <button onClick={() => setEditing("new")} className="text-primary underline underline-offset-2">Add a camera</button> — pick a vendor profile, enter host and credentials, test, save. Use the <b>Synthetic test feed</b> profile for a demo without hardware.
        </div>
      )}

      <div className="space-y-3">
        {cameras.map((cam) => (
          <CameraCard
            key={cam.id}
            camera={cam}
            onEdit={() => setEditing(cam)}
            onChanged={upsert}
            onDeleted={() => { setCameras((prev) => prev.filter((c) => c.id !== cam.id)); if (editing !== "new" && editing?.id === cam.id) setEditing(null); }}
          />
        ))}
      </div>
    </div>
  );
}
