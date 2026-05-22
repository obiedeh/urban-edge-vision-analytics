import { useEffect, useState } from "react";
import { api, type Camera, type Binding, type UseCasePack, ApiError } from "@/lib/api";
import { PackToggleGrid } from "@/components/pack-toggle-grid";
import { ZoneEditor } from "@/components/zone-editor";
import { cn } from "@/lib/utils";
import { ChevronDown, ChevronRight, Save, AlertCircle, CheckCircle } from "lucide-react";

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
        Define two parallel virtual gates (A and B) that vehicles cross. The distance between
        them determines speed calculation accuracy.
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
        Define the stop zone polygon. Vehicles that fail to dwell at minimum speed inside
        this region will trigger a stop sign violation event.
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
      const updated = await api.cameras.putBindings(cameraId, bindings);
      setBindings(updated);
      setSavedPackSet(activeKey(updated));
      setStatus({ kind: "ok", text: "Pack bindings saved." });
    } catch (e) {
      if (e instanceof ApiError) {
        const detail = e.detail?.detail ?? e.detail;
        const errCode =
          typeof detail === "object" && detail !== null
            ? (detail as Record<string, unknown>).error
            : null;
        const msg =
          errCode === "incompatible_pack_selection"
            ? "Incompatible pack combination (§11.4 rule)."
            : errCode === "missing_prerequisite"
            ? "A pack requires another pack to be active first."
            : errCode === "invalid_report_interval"
            ? "Report interval must be at least 2 seconds."
            : `API error ${e.status}`;
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

// ── Active packs for selected camera ─────────────────────────────────────────

function hasActivePack(bindings: Binding[], packId: string) {
  return bindings.some((b) => b.pack_id === packId && b.enabled);
}

function CameraStudio({
  camera,
  packs,
}: {
  camera: Camera;
  packs: UseCasePack[];
}) {
  const [bindings, setBindings] = useState<Binding[]>([]);

  useEffect(() => {
    api.cameras.bindings(camera.id).then(setBindings).catch(() => null);
  }, [camera.id]);

  const hasSpeed = hasActivePack(bindings, "speed_violation");
  const hasStop = hasActivePack(bindings, "stop_sign");

  return (
    <div className="space-y-3">
      <Section title="Use Case Packs">
        <BindingsSection cameraId={camera.id} packs={packs} />
      </Section>

      {hasSpeed && (
        <Section title="Speed Calibration" defaultOpen={false}>
          <SpeedCalibSection cameraId={camera.id} />
        </Section>
      )}

      {hasStop && (
        <Section title="Stop Zone" defaultOpen={false}>
          <StopZoneSection cameraId={camera.id} />
        </Section>
      )}
    </div>
  );
}

// ── Root page ─────────────────────────────────────────────────────────────────

export function UseCaseStudio() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [packs, setPacks] = useState<UseCasePack[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.cameras.list(), api.useCases.list()])
      .then(([cams, ps]) => {
        setCameras(cams);
        setPacks(ps);
        if (cams.length > 0) setSelectedId(cams[0].id);
      })
      .catch(() => null)
      .finally(() => setLoading(false));
  }, []);

  const selected = cameras.find((c) => c.id === selectedId) ?? null;

  return (
    <div className="p-4 space-y-4">
      <h1 className="text-lg font-semibold">Use Case Studio</h1>

      {loading && (
        <p className="text-sm text-muted-foreground">Loading cameras…</p>
      )}

      {!loading && cameras.length === 0 && (
        <div className="rounded-lg border border-border bg-card px-4 py-8 text-center text-sm text-muted-foreground">
          No cameras configured. Add cameras via{" "}
          <code className="text-primary">configs/camera.local.json</code> or the API.
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
              <button
                key={cam.id}
                onClick={() => setSelectedId(cam.id)}
                className={cn(
                  "w-full text-left rounded px-3 py-2 text-sm transition-colors",
                  cam.id === selectedId
                    ? "bg-primary/15 text-primary font-medium"
                    : "text-muted-foreground hover:text-foreground hover:bg-secondary"
                )}
              >
                {cam.name || cam.id}
              </button>
            ))}
          </div>

          {/* Config panels */}
          <div className="lg:col-span-3">
            {selected && (
              <CameraStudio camera={selected} packs={packs} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
