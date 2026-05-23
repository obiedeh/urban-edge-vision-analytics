import { useEffect, useState } from "react";
import { api, type Camera, type Binding, type UseCasePack, ApiError, type CameraConfigResponse } from "@/lib/api";
import { PackToggleGrid } from "@/components/pack-toggle-grid";
import { ZoneEditor } from "@/components/zone-editor";
import { CameraConfigForm } from "@/components/camera-config-form";
import { cn } from "@/lib/utils";
import { ChevronDown, ChevronRight, Save, AlertCircle, CheckCircle, PlusCircle, Pencil } from "lucide-react";

// ── Helpers ──────────────────────────────────────────────────────────────────

function Section({
  title,
  children,
  defaultOpen = true,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium text-foreground"
      >
        {title}
        {open ? (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        )}
      </button>
      {open && <div className="border-t border-border px-4 py-4">{children}</div>}
    </div>
  );
}

function StatusMsg({
  kind,
  text,
}: {
  kind: "ok" | "err";
  text: string;
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded px-3 py-2 text-xs",
        kind === "ok"
          ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
          : "bg-red-500/10 text-red-400 border border-red-500/30"
      )}
    >
      {kind === "ok" ? (
        <CheckCircle className="h-3.5 w-3.5 shrink-0" />
      ) : (
        <AlertCircle className="h-3.5 w-3.5 shrink-0" />
      )}
      {text}
    </div>
  );
}

// ── Calibration wizard (speed) ────────────────────────────────────────────────

interface GateEditorProps {
  label: string;
  gate: number[][];
  onChange: (pts: number[][]) => void;
}

function GateEditor({ label, gate, onChange }: GateEditorProps) {
  // Proxy between ZoneEditor's {x,y} and backend's [[x,y],...] arrays
  const pts = gate.map(([x, y]) => ({ x, y }));
  return (
    <ZoneEditor
      label={label}
      points={pts}
      onChange={(updated) => onChange(updated.map((p) => [p.x, p.y]))}
    />
  );
}

function SpeedCalibSection({ cameraId }: { cameraId: string }) {
  const [gateA, setGateA] = useState<number[][]>([]);
  const [gateB, setGateB] = useState<number[][]>([]);
  const [distance, setDistance] = useState("10");
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    api.cameras
      .speedCalibration(cameraId)
      .then((cal) => {
        setGateA(cal.gate_a ?? []);
        setGateB(cal.gate_b ?? []);
        setDistance(String(cal.real_world_distance_m ?? 10));
      })
      .catch(() => null);
  }, [cameraId]);

  async function save() {
    setSaving(true);
    setStatus(null);
    try {
      await api.cameras.putSpeedCalibration(cameraId, {
        camera_id: cameraId,
        gate_a: gateA,
        gate_b: gateB,
        real_world_distance_m: parseFloat(distance) || 10,
      });
      setStatus({ kind: "ok", text: "Speed calibration saved." });
    } catch (e) {
      setStatus({ kind: "err", text: e instanceof Error ? e.message : "Save failed" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Required for Speed Violation pack.</span>{" "}
        Define two parallel virtual gates (A and B) across the lane. The real-world distance
        between them determines speed calculation accuracy. Configure this before enabling
        the Speed Violation pack above.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <GateEditor label="Gate A" gate={gateA} onChange={setGateA} />
        <GateEditor label="Gate B" gate={gateB} onChange={setGateB} />
      </div>
      <div className="flex items-center gap-3">
        <label className="text-xs text-muted-foreground w-40">
          Real-world distance (m)
        </label>
        <input
          type="number"
          min={1}
          step={0.5}
          value={distance}
          onChange={(e) => setDistance(e.target.value)}
          className="w-24 rounded border border-input bg-background px-2 py-1 text-xs text-foreground"
        />
      </div>
      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={save}
          disabled={saving}
          className="flex items-center gap-1.5 rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          <Save className="h-3 w-3" />
          {saving ? "Saving…" : "Save calibration"}
        </button>
        {status && <StatusMsg kind={status.kind} text={status.text} />}
      </div>
    </div>
  );
}

// ── Stop zone editor ──────────────────────────────────────────────────────────

function StopZoneSection({ cameraId }: { cameraId: string }) {
  const [pts, setPts] = useState<{ x: number; y: number }[]>([]);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    api.cameras
      .stopZone(cameraId)
      .then((z) => {
        const poly = z.polygon as number[][] | undefined;
        if (Array.isArray(poly)) {
          setPts(poly.map(([x, y]) => ({ x, y })));
        }
      })
      .catch(() => null);
  }, [cameraId]);

  async function save() {
    setSaving(true);
    setStatus(null);
    try {
      await api.cameras.putStopZone(cameraId, {
        camera_id: cameraId,
        polygon: pts.map((p) => [p.x, p.y]),
      });
      setStatus({ kind: "ok", text: "Stop zone saved." });
    } catch (e) {
      setStatus({ kind: "err", text: e instanceof Error ? e.message : "Save failed" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Required for Stop Sign pack.</span>{" "}
        Draw the stop zone polygon over the stop bar area. Vehicles that fail to dwell at
        minimum speed inside this region trigger a stop sign violation. Configure this before
        enabling the Stop Sign pack above.
      </p>
      <ZoneEditor
        label="Stop zone polygon"
        points={pts}
        onChange={setPts}
      />
      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={save}
          disabled={saving}
          className="flex items-center gap-1.5 rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          <Save className="h-3 w-3" />
          {saving ? "Saving…" : "Save stop zone"}
        </button>
        {status && <StatusMsg kind={status.kind} text={status.text} />}
      </div>
    </div>
  );
}

// ── Pack bindings (with report interval) ─────────────────────────────────────

function BindingsSection({
  cameraId,
  packs,
}: {
  cameraId: string;
  packs: UseCasePack[];
}) {
  const [bindings, setBindings] = useState<Binding[]>([]);
  // Track the server-committed set so we can detect pack-set changes
  const [savedPackSet, setSavedPackSet] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    api.cameras.bindings(cameraId).then((b) => {
      setBindings(b);
      setSavedPackSet(activeKey(b));
    }).catch(() => null);
  }, [cameraId]);

  /** Stable key representing which packs are enabled */
  function activeKey(b: Binding[]) {
    return b
      .filter((x) => x.enabled)
      .map((x) => x.pack_id)
      .sort()
      .join("+");
  }

  async function save() {
    // Require explicit confirmation when the pack selection itself changes
    const newPackSet = activeKey(bindings);
    if (newPackSet !== savedPackSet) {
      const confirmed = window.confirm(
        "Changing the active pack set will update what this camera detects and writes an audit record.\n\nProceed?"
      );
      if (!confirmed) return;
    }

    setSaving(true);
    setStatus(null);
    try {
      await api.cameras.putBindings(cameraId, bindings);
      // Re-fetch the authoritative list from the server
      const refreshed = await api.cameras.bindings(cameraId);
      setBindings(refreshed);
      setSavedPackSet(activeKey(refreshed));
      setStatus({ kind: "ok", text: "Pack bindings saved." });
    } catch (e) {
      if (e instanceof ApiError) {
        const detail = e.detail?.detail ?? e.detail;
        const d = typeof detail === "object" && detail !== null
          ? (detail as Record<string, unknown>)
          : null;
        const errCode = d?.error as string | undefined;

        let msg: string;
        if (errCode === "incompatible_pack_selection") {
          msg = "Incompatible pack combination — Pack 2 (Speed) and Pack 3 (Stop Sign) cannot share the same camera.";
        } else if (errCode === "missing_prerequisite") {
          const pack = d?.pack_id as string | undefined;
          const prereq = d?.prerequisite as string | undefined;
          if (pack === "speed_violation" || prereq === "speed_calibration") {
            msg = "Speed Violation pack requires speed calibration to be configured for this camera first. Set up gate A and gate B in the Speed Calibration section.";
          } else if (pack === "stop_sign" || prereq === "stop_zone") {
            msg = "Stop Sign pack requires a stop zone to be drawn for this camera first. Define the stop zone in the Stop Zone section.";
          } else {
            msg = (d?.message as string) || "A required configuration is missing for one of the selected packs.";
          }
        } else if (errCode === "invalid_report_interval") {
          msg = "Report interval must be at least 2 seconds.";
        } else {
          msg = (d?.message as string) || `API error ${e.status}`;
        }
        setStatus({ kind: "err", text: msg });
      } else {
        setStatus({ kind: "err", text: e instanceof Error ? e.message : "Save failed" });
      }
    } finally {
      setSaving(false);
    }
  }

  const activeBindings = bindings.filter((b) => b.enabled);

  return (
    <div className="space-y-4">
      <PackToggleGrid packs={packs} bindings={bindings} onChange={setBindings} disabled={saving} />

      {activeBindings.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">Report interval (seconds)</p>
          {activeBindings.map((b) => (
            <div key={b.pack_id} className="flex items-center gap-3">
              <span className="text-xs text-foreground w-36 font-mono">{b.pack_id}</span>
              <input
                type="number"
                min={2}
                max={300}
                value={b.report_interval_seconds}
                onChange={(e) => {
                  const val = Math.max(2, parseInt(e.target.value) || 2);
                  setBindings((prev) =>
                    prev.map((x) =>
                      x.pack_id === b.pack_id
                        ? { ...x, report_interval_seconds: val }
                        : x
                    )
                  );
                }}
                className="w-20 rounded border border-input bg-background px-2 py-1 text-xs text-foreground"
              />
              <span className="text-xs text-muted-foreground">s (min 2)</span>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={save}
          disabled={saving}
          className="flex items-center gap-1.5 rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          <Save className="h-3 w-3" />
          {saving ? "Saving…" : "Save bindings"}
        </button>
        {status && <StatusMsg kind={status.kind} text={status.text} />}
      </div>
    </div>
  );
}

function CameraStudio({
  camera,
  packs,
}: {
  camera: Camera;
  packs: UseCasePack[];
}) {
  return (
    <div className="space-y-3">
      <Section title="Use Case Packs">
        <BindingsSection cameraId={camera.id} packs={packs} />
      </Section>

      {/* Always shown so users can configure prerequisites before enabling the pack */}
      <Section title="⚡ Speed Calibration" defaultOpen={false}>
        <SpeedCalibSection cameraId={camera.id} />
      </Section>

      <Section title="🛑 Stop Zone" defaultOpen={false}>
        <StopZoneSection cameraId={camera.id} />
      </Section>
    </div>
  );
}

// ── Root page ─────────────────────────────────────────────────────────────────

export function UseCaseStudio() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [packs, setPacks] = useState<UseCasePack[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showConfig, setShowConfig] = useState(false);
  const [editingCamera, setEditingCamera] = useState<Camera | null>(null);

  function loadCameras() {
    return Promise.all([api.cameras.list(), api.useCases.list()])
      .then(([cams, ps]) => {
        setCameras(cams);
        setPacks(ps);
        if (cams.length > 0 && !selectedId) setSelectedId(cams[0].id);
      })
      .catch(() => null)
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadCameras();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleCameraSaved(res: CameraConfigResponse) {
    // Refresh camera list and auto-select the newly saved camera
    Promise.all([api.cameras.list(), api.useCases.list()])
      .then(([cams, ps]) => {
        setCameras(cams);
        setPacks(ps);
        setSelectedId(res.camera_id);
        setShowConfig(false);
        setEditingCamera(null);
      })
      .catch(() => null);
  }

  function handleCameraDeleted() {
    // Refresh list after removal
    api.cameras.list()
      .then((cams) => {
        setCameras(cams);
        if (cams.length > 0) setSelectedId(cams[0].id);
        else setSelectedId(null);
      })
      .catch(() => null);
  }

  const selected = cameras.find((c) => c.id === selectedId) ?? null;

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-lg font-semibold">Use Case Studio</h1>
        <div className="flex items-center gap-1.5">
          {/* Update Config — only when a camera is selected */}
          {cameras.length > 0 && selected && (
            <button
              onClick={() => {
                if (showConfig && editingCamera?.id === selected.id) {
                  setShowConfig(false);
                  setEditingCamera(null);
                } else {
                  setEditingCamera(selected);
                  setShowConfig(true);
                }
              }}
              className={cn(
                "flex items-center gap-1.5 rounded border px-3 py-1.5 text-xs font-medium transition-colors",
                showConfig && editingCamera?.id === selected.id
                  ? "border-primary/50 bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:text-foreground hover:border-primary/40"
              )}
            >
              <Pencil className="h-3.5 w-3.5" />
              Update Config
            </button>
          )}

          {/* Add Camera */}
          <button
            onClick={() => {
              if (showConfig && !editingCamera) {
                setShowConfig(false);
              } else {
                setEditingCamera(null);
                setShowConfig(true);
              }
            }}
            className={cn(
              "flex items-center gap-1.5 rounded border px-3 py-1.5 text-xs font-medium transition-colors",
              showConfig && !editingCamera
                ? "border-primary/50 bg-primary/10 text-primary"
                : "border-border text-muted-foreground hover:text-foreground hover:border-primary/40"
            )}
          >
            <PlusCircle className="h-3.5 w-3.5" />
            Add Camera
          </button>
        </div>
      </div>

      {/* Camera config form — shown when toggled OR when there are no cameras yet */}
      {(showConfig || (!loading && cameras.length === 0)) && (
        <div className="rounded-lg border border-border bg-card px-5 py-5">
          <CameraConfigForm
            prefillCamera={editingCamera ?? undefined}
            onSaved={handleCameraSaved}
            onDeleted={handleCameraDeleted}
          />
        </div>
      )}

      {loading && (
        <p className="text-sm text-muted-foreground">Loading cameras…</p>
      )}

      {!loading && cameras.length === 0 && !showConfig && (
        <div className="rounded-lg border border-dashed border-border bg-card/50 px-4 py-8 text-center text-sm text-muted-foreground">
          No cameras configured yet. Click{" "}
          <button
            onClick={() => setShowConfig(true)}
            className="text-primary underline underline-offset-2"
          >
            Add Camera
          </button>{" "}
          above to get started.
        </div>
      )}

      {!loading && cameras.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
          {/* Camera picker sidebar */}
          <div className="space-y-1">
            <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">
              Cameras
            </p>
            {cameras.map((cam) => (
              <div
                key={cam.id}
                className={cn(
                  "flex items-center group rounded transition-colors",
                  cam.id === selectedId ? "bg-primary/15" : "hover:bg-secondary"
                )}
              >
                {/* Select camera (name click) */}
                <button
                  onClick={() => { setSelectedId(cam.id); setShowConfig(false); setEditingCamera(null); }}
                  className={cn(
                    "flex-1 text-left px-3 py-2 text-sm transition-colors",
                    cam.id === selectedId
                      ? "text-primary font-medium"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  <span className="flex items-center gap-1.5 flex-wrap">
                    {cam.name || cam.id}
                    {cam.synthetic ? (
                      <span className="text-[9px] px-1 py-0.5 rounded border bg-yellow-500/15 text-yellow-400 border-yellow-500/30 font-semibold">SYNTH</span>
                    ) : (
                      <span className="text-[9px] px-1 py-0.5 rounded border bg-emerald-500/15 text-emerald-400 border-emerald-500/30 font-semibold">LIVE</span>
                    )}
                  </span>
                </button>

                {/* Edit config for this camera */}
                <button
                  onClick={() => {
                    setSelectedId(cam.id);
                    setEditingCamera(cam);
                    setShowConfig(true);
                  }}
                  title={`Edit config for ${cam.name || cam.id}`}
                  className={cn(
                    "px-2 py-2 text-muted-foreground hover:text-primary transition-all",
                    "opacity-0 group-hover:opacity-100 focus:opacity-100"
                  )}
                >
                  <Pencil className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>

          {/* Config panels */}
          <div className="lg:col-span-3">
            {selected && !showConfig && (
              <CameraStudio camera={selected} packs={packs} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
