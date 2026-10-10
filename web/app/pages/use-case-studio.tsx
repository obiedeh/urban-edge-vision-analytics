import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  api, ApiError, apiErrorMessage,
  type Binding, type Camera, type Point, type SpeedCalibration, type StopZone, type UseCasePack,
} from "@/lib/api";
import { PackToggleGrid } from "@/components/pack-toggle-grid";
import { ZoneCanvas, PointList, type Shape } from "@/components/zone-canvas";
import { CameraStateChip, ProfileChip, StatusMsg } from "@/components/status-chip";
import { cn, inputCls, selectCls, btnPrimary } from "@/lib/utils";
import { Save, Loader2, ChevronDown, ChevronRight } from "lucide-react";

type Msg = { kind: "ok" | "err" | "warn"; text: string } | null;

function Section({ title, children, defaultOpen = true, badge }: { title: string; children: React.ReactNode; defaultOpen?: boolean; badge?: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-lg border border-border bg-card">
      <button onClick={() => setOpen((v) => !v)} className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium text-foreground">
        <span className="flex items-center gap-2">{title}{badge}</span>
        {open ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
      </button>
      {open && <div className="border-t border-border px-4 py-4">{children}</div>}
    </div>
  );
}

// ── Bindings ──────────────────────────────────────────────────────────────────

/** UI binding = server binding + enabled flag (server only stores enabled ones). */
interface UiBinding extends Binding { enabled: boolean }

/** vehicle_count binding parameters edited in the "Count line" zone-editor mode. */
interface CountConfig {
  count_line: Point[];
  label_a_to_b: string;
  label_b_to_a: string;
  classes: string[];
  min_observations: number;
}
const COUNT_CLASSES = ["car", "truck", "bus", "motorcycle"];
const DEFAULT_COUNT: CountConfig = { count_line: [], label_a_to_b: "", label_b_to_a: "", classes: [...COUNT_CLASSES], min_observations: 2 };

function countFromParams(p: Record<string, unknown> | undefined): CountConfig {
  const line = Array.isArray(p?.count_line) ? (p!.count_line as Point[]) : [];
  return {
    count_line: line,
    label_a_to_b: typeof p?.label_a_to_b === "string" ? p.label_a_to_b : "",
    label_b_to_a: typeof p?.label_b_to_a === "string" ? p.label_b_to_a : "",
    classes: Array.isArray(p?.classes) ? (p!.classes as string[]) : [...COUNT_CLASSES],
    min_observations: typeof p?.min_observations === "number" ? p.min_observations : 2,
  };
}
/** Blank labels are omitted so the pack's defaults ("a_to_b" / "b_to_a") apply. */
function countToParams(c: CountConfig): Record<string, unknown> {
  const out: Record<string, unknown> = { count_line: c.count_line, classes: c.classes, min_observations: c.min_observations };
  if (c.label_a_to_b.trim()) out.label_a_to_b = c.label_a_to_b.trim();
  if (c.label_b_to_a.trim()) out.label_b_to_a = c.label_b_to_a.trim();
  return out;
}

function bindingsErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const detail = e.detail?.detail ?? e.detail;
    const d = typeof detail === "object" && detail !== null ? (detail as Record<string, unknown>) : null;
    const code = d?.error as string | undefined;
    if (code === "incompatible_pack_selection") return "Incompatible pack combination — Speed Violation and Stop Sign cannot share one camera.";
    if (code === "missing_prerequisite") {
      const prereq = d?.prerequisite as string | undefined;
      if (prereq === "speed_calibration") return "Speed Violation needs a saved speed calibration (gate A, gate B, distance) for this camera first. Draw it in the zone editor below and save.";
      if (prereq === "stop_zone") return "Stop Sign needs a saved stop zone for this camera first. Draw it in the zone editor below and save.";
      if (prereq === "count_line") return "Vehicle Count needs a two-point count line (A→B). Draw it in the zone editor below (Count line mode) and save bindings again.";
      return (d?.message as string) || "A prerequisite is missing for one of the selected packs.";
    }
    if (code === "invalid_report_interval") return "Report interval must be at least 2 seconds.";
  }
  return apiErrorMessage(e, "Save failed");
}

function toUi(rows: Binding[]): UiBinding[] {
  return rows.map((r) => ({ pack_id: r.pack_id, parameters: r.parameters ?? {}, report_interval_seconds: r.report_interval_seconds, enabled: true }));
}

function BindingsSection({
  cameraId, packs, movingZone, count, onLoaded, onChange,
}: {
  cameraId: string;
  packs: UseCasePack[];
  /** moving_object zone drawn in the editor (saved into binding.parameters.zone) */
  movingZone: Point[];
  /** vehicle_count line + labels drawn/typed in the editor (saved as the binding's parameters) */
  count: CountConfig;
  /** server-confirmed bindings (initial load and after save) */
  onLoaded: (b: UiBinding[]) => void;
  /** unsaved toggles / edits */
  onChange: (b: UiBinding[]) => void;
}) {
  const [bindings, setBindings] = useState<UiBinding[]>([]);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<Msg>(null);
  // Latest callbacks for the async load without re-running the fetch on every parent render.
  const onLoadedRef = useRef(onLoaded);
  onLoadedRef.current = onLoaded;

  useEffect(() => {
    let dead = false;
    api.cameras.bindings(cameraId).then((rows) => {
      if (dead) return;
      const ui = toUi(rows);
      setBindings(ui); onLoadedRef.current(ui);
    }).catch(() => null);
    return () => { dead = true; };
  }, [cameraId]);

  const moving = bindings.find((b) => b.pack_id === "moving_object" && b.enabled);
  const movingParams = (moving?.parameters ?? {}) as { target_classes?: string[]; min_observations?: number };

  function update(next: UiBinding[]) { setBindings(next); onChange(next); setMsg(null); }
  function setMovingParam(key: string, value: unknown) {
    update(bindings.map((b) => (b.pack_id === "moving_object" ? { ...b, parameters: { ...b.parameters, [key]: value } } : b)));
  }

  async function save() {
    setSaving(true); setMsg(null);
    try {
      const active = bindings.filter((b) => b.enabled).map((b) => {
        const params = { ...b.parameters };
        if (b.pack_id === "moving_object") params.zone = movingZone;
        if (b.pack_id === "vehicle_count") { delete params.label_a_to_b; delete params.label_b_to_a; Object.assign(params, countToParams(count)); }
        return { pack_id: b.pack_id, parameters: params, report_interval_seconds: b.report_interval_seconds };
      });
      await api.cameras.putBindings(cameraId, active);
      const ui = toUi(await api.cameras.bindings(cameraId));
      setBindings(ui); onLoadedRef.current(ui);
      setMsg({ kind: "ok", text: `Saved ${ui.length} binding${ui.length === 1 ? "" : "s"} — applied live.` });
    } catch (e) { setMsg({ kind: "err", text: bindingsErrorMessage(e) }); }
    finally { setSaving(false); }
  }

  const active = bindings.filter((b) => b.enabled);
  return (
    <div className="space-y-4">
      <PackToggleGrid packs={packs} bindings={bindings} onChange={(b) => update(b as UiBinding[])} disabled={saving} />
      {active.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">Report interval (seconds, min 2)</p>
          {active.map((b) => (
            <div key={b.pack_id} className="flex items-center gap-3">
              <span className="text-xs text-foreground w-36 font-mono">{b.pack_id}</span>
              <input type="number" min={2} max={300} value={b.report_interval_seconds}
                onChange={(e) => update(bindings.map((x) => x.pack_id === b.pack_id ? { ...x, report_interval_seconds: Math.max(2, parseInt(e.target.value) || 2) } : x))}
                className={cn(inputCls, "w-20")} />
            </div>
          ))}
        </div>
      )}
      {moving && (
        <div className="rounded border border-border bg-secondary/10 px-3 py-3 space-y-2">
          <p className="text-xs font-medium text-foreground">Moving Object parameters</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="space-y-1 text-xs text-muted-foreground">Target classes (comma separated)
              <input value={(movingParams.target_classes ?? ["pedestrian"]).join(", ")} onChange={(e) => setMovingParam("target_classes", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} className={inputCls} placeholder="pedestrian, cyclist" />
            </label>
            <label className="space-y-1 text-xs text-muted-foreground">Min observations before reporting
              <input type="number" min={1} value={movingParams.min_observations ?? 2} onChange={(e) => setMovingParam("min_observations", Math.max(1, parseInt(e.target.value) || 1))} className={inputCls} />
            </label>
          </div>
          <p className="text-[10px] text-muted-foreground/70">
            Zone: {movingZone.length >= 3 ? `${movingZone.length}-point polygon (drawn below, saved with the binding)` : "none — whole frame. Draw a Moving-object zone below to restrict it."}
          </p>
        </div>
      )}
      {bindings.some((b) => b.pack_id === "vehicle_count" && b.enabled) && (
        <div className="rounded border border-border bg-secondary/10 px-3 py-3 space-y-1">
          <p className="text-xs font-medium text-foreground">Vehicle Count parameters</p>
          <p className="text-[10px] text-muted-foreground/70">
            Count line: {count.count_line.length === 2 ? `A (${count.count_line[0][0]}, ${count.count_line[0][1]}) → B (${count.count_line[1][0]}, ${count.count_line[1][1]})` : "not drawn — required. Use Count line mode in the zone editor below."}
            {" · "}classes {count.classes.join(", ") || "none"} · labels {count.label_a_to_b.trim() || "a_to_b"} / {count.label_b_to_a.trim() || "b_to_a"} · min obs {count.min_observations}
          </p>
        </div>
      )}
      <div className="flex items-center gap-3 flex-wrap">
        <button onClick={save} disabled={saving} className={btnPrimary}>{saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />} Save bindings</button>
        {msg && <StatusMsg kind={msg.kind} text={msg.text} />}
      </div>
    </div>
  );
}

// ── Zone editor ───────────────────────────────────────────────────────────────

type Mode = "stop" | "speed" | "moving" | "count";
const COLORS = { stop: "#ef4444", gateA: "#38bdf8", gateB: "#a78bfa", moving: "#34d399", count: "#fbbf24" };

function ZoneEditorSection({
  cameraId, movingZone, setMovingZone, movingEnabled, count, setCount, countEnabled,
}: {
  cameraId: string;
  movingZone: Point[];
  setMovingZone: (p: Point[]) => void;
  movingEnabled: boolean;
  count: CountConfig;
  setCount: (c: CountConfig) => void;
  countEnabled: boolean;
}) {
  const [mode, setMode] = useState<Mode>("stop");
  const [activeId, setActiveId] = useState<string>("stop");

  // Stop zone
  const [stopPoly, setStopPoly] = useState<Point[]>([]);
  const [approach, setApproach] = useState("N");
  const [thr, setThr] = useState<{ dwell_threshold_ms: number; stop_speed_threshold: number; rolling_speed_threshold: number; report_compliant: boolean }>({
    dwell_threshold_ms: 1000, stop_speed_threshold: 0.02, rolling_speed_threshold: 0.08, report_compliant: false,
  });
  const [stopMsg, setStopMsg] = useState<Msg>(null);
  const [stopSaving, setStopSaving] = useState(false);
  const [hasStop, setHasStop] = useState(false);

  // Speed gates
  const [gateA, setGateA] = useState<Point[]>([]);
  const [gateB, setGateB] = useState<Point[]>([]);
  const [distance, setDistance] = useState("10");
  const [posted, setPosted] = useState("50");
  const [speedMsg, setSpeedMsg] = useState<Msg>(null);
  const [speedSaving, setSpeedSaving] = useState(false);
  const [hasSpeed, setHasSpeed] = useState(false);

  useEffect(() => {
    let dead = false;
    setStopPoly([]); setGateA([]); setGateB([]); setHasStop(false); setHasSpeed(false); setStopMsg(null); setSpeedMsg(null);
    api.cameras.stopZone(cameraId).then((z: StopZone) => {
      if (dead) return;
      setStopPoly((z.polygon ?? []) as Point[]); setApproach(z.approach_direction ?? "N"); setHasStop(true);
      const t = z.compliance_thresholds ?? {};
      setThr((prev) => ({
        dwell_threshold_ms: t.dwell_threshold_ms ?? prev.dwell_threshold_ms,
        stop_speed_threshold: t.stop_speed_threshold ?? prev.stop_speed_threshold,
        rolling_speed_threshold: t.rolling_speed_threshold ?? prev.rolling_speed_threshold,
        report_compliant: t.report_compliant ?? prev.report_compliant,
      }));
    }).catch(() => null);
    api.cameras.speedCalibration(cameraId).then((c: SpeedCalibration) => {
      if (dead) return;
      setGateA((c.gate_a ?? []) as Point[]); setGateB((c.gate_b ?? []) as Point[]);
      setDistance(String(c.real_world_distance_m ?? 10)); setPosted(String(c.posted_speed_kph ?? 50)); setHasSpeed(true);
    }).catch(() => null);
    return () => { dead = true; };
  }, [cameraId]);

  useEffect(() => { setActiveId(mode === "stop" ? "stop" : mode === "speed" ? "gateA" : mode === "moving" ? "moving" : "count"); }, [mode]);

  const shapes: Shape[] = useMemo(() => [
    { id: "stop", label: "Stop zone", points: stopPoly, color: COLORS.stop, kind: "polygon" },
    { id: "gateA", label: "Gate A", points: gateA, color: COLORS.gateA, kind: gateA.length >= 3 ? "polygon" : "line" },
    { id: "gateB", label: "Gate B", points: gateB, color: COLORS.gateB, kind: gateB.length >= 3 ? "polygon" : "line" },
    { id: "moving", label: "Moving-object zone", points: movingZone, color: COLORS.moving, kind: "polygon" },
    { id: "count", label: "Count line", points: count.count_line, color: COLORS.count, kind: "arrow", maxPoints: 2, pointLabels: ["A", "B"] },
  ], [stopPoly, gateA, gateB, movingZone, count.count_line]);

  function onShapeChange(id: string, pts: Point[]) {
    if (id === "stop") { setStopPoly(pts); setStopMsg(null); }
    else if (id === "gateA") { setGateA(pts); setSpeedMsg(null); }
    else if (id === "gateB") { setGateB(pts); setSpeedMsg(null); }
    else if (id === "moving") setMovingZone(pts);
    else if (id === "count") setCount({ ...count, count_line: pts.slice(0, 2) });
  }

  async function saveStop() {
    if (stopPoly.length < 3) { setStopMsg({ kind: "err", text: "A stop zone needs at least 3 points." }); return; }
    setStopSaving(true); setStopMsg(null);
    try {
      await api.cameras.putStopZone(cameraId, { polygon: stopPoly, approach_direction: approach, compliance_thresholds: thr });
      setHasStop(true); setStopMsg({ kind: "ok", text: "Stop zone saved — applied live." });
    } catch (e) { setStopMsg({ kind: "err", text: apiErrorMessage(e, "Save failed") }); }
    finally { setStopSaving(false); }
  }

  async function saveSpeed() {
    if (gateA.length < 2 || gateB.length < 2) { setSpeedMsg({ kind: "err", text: "Each gate needs at least 2 points (a line) or 3+ (a polygon)." }); return; }
    const dist = parseFloat(distance), kph = parseFloat(posted);
    if (!(dist > 0) || !(kph > 0)) { setSpeedMsg({ kind: "err", text: "Distance and posted speed must be positive." }); return; }
    setSpeedSaving(true); setSpeedMsg(null);
    try {
      await api.cameras.putSpeedCalibration(cameraId, { gate_a: gateA, gate_b: gateB, real_world_distance_m: dist, posted_speed_kph: kph });
      setHasSpeed(true); setSpeedMsg({ kind: "ok", text: "Speed calibration saved — applied live." });
    } catch (e) { setSpeedMsg({ kind: "err", text: apiErrorMessage(e, "Save failed") }); }
    finally { setSpeedSaving(false); }
  }

  const ModeBtn = ({ m, label, color, saved }: { m: Mode; label: string; color: string; saved?: boolean }) => (
    <button onClick={() => setMode(m)} className={cn("flex items-center gap-1.5 rounded border px-2.5 py-1 text-xs transition-colors", mode === m ? "border-primary/60 bg-primary/15 text-foreground" : "border-border text-muted-foreground hover:text-foreground")}>
      <span className="h-2 w-2 rounded-full" style={{ background: color }} /> {label}
      {saved && <span className="text-[9px] text-emerald-400">saved</span>}
    </button>
  );

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <ModeBtn m="stop" label="Stop zone" color={COLORS.stop} saved={hasStop} />
        <ModeBtn m="speed" label="Speed gates" color={COLORS.gateA} saved={hasSpeed} />
        <ModeBtn m="moving" label="Moving-object zone" color={COLORS.moving} saved={movingZone.length >= 3} />
        <ModeBtn m="count" label="Count line" color={COLORS.count} saved={count.count_line.length === 2} />
        <span className="text-[10px] text-muted-foreground ml-auto">All coordinates normalized 0..1 relative to the frame.</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <ZoneCanvas cameraId={cameraId} shapes={shapes} activeId={activeId} onChange={onShapeChange} />
        </div>

        <div className="space-y-3 text-xs">
          {mode === "stop" && (
            <>
              <p className="text-muted-foreground">Polygon over the stop bar area. Vehicles whose ground point enters it are judged compliant / rolling stop / no stop.</p>
              <PointList points={stopPoly} onChange={(p) => onShapeChange("stop", p)} color={COLORS.stop} />
              <label className="block space-y-1 text-muted-foreground">Approach direction
                <select value={approach} onChange={(e) => setApproach(e.target.value)} className={selectCls}>
                  {["N", "S", "E", "W", "NE", "NW", "SE", "SW"].map((d) => <option key={d}>{d}</option>)}
                </select>
              </label>
              <div className="grid grid-cols-2 gap-2">
                <label className="space-y-1 text-muted-foreground">Dwell threshold (ms)
                  <input type="number" min={0} step={100} value={thr.dwell_threshold_ms} onChange={(e) => setThr({ ...thr, dwell_threshold_ms: parseInt(e.target.value) || 0 })} className={inputCls} />
                </label>
                <label className="space-y-1 text-muted-foreground">Stop speed threshold
                  <input type="number" min={0} step={0.005} value={thr.stop_speed_threshold} onChange={(e) => setThr({ ...thr, stop_speed_threshold: parseFloat(e.target.value) || 0 })} className={inputCls} />
                </label>
                <label className="space-y-1 text-muted-foreground">Rolling speed threshold
                  <input type="number" min={0} step={0.005} value={thr.rolling_speed_threshold} onChange={(e) => setThr({ ...thr, rolling_speed_threshold: parseFloat(e.target.value) || 0 })} className={inputCls} />
                </label>
                <label className="flex items-center gap-2 text-muted-foreground self-end pb-1.5">
                  <input type="checkbox" checked={thr.report_compliant} onChange={(e) => setThr({ ...thr, report_compliant: e.target.checked })} className="rounded border-input bg-background" /> Report compliant stops too
                </label>
              </div>
              <button onClick={saveStop} disabled={stopSaving} className={btnPrimary}>{stopSaving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />} Save stop zone</button>
              {stopMsg && <StatusMsg kind={stopMsg.kind} text={stopMsg.text} />}
            </>
          )}

          {mode === "speed" && (
            <>
              <p className="text-muted-foreground">Two gates across the lane; 2 points make a line, 3+ a polygon. The real-world distance between them calibrates speed.</p>
              <div className="flex items-center gap-1">
                {(["gateA", "gateB"] as const).map((g) => (
                  <button key={g} onClick={() => setActiveId(g)} className={cn("rounded border px-2 py-0.5 text-[11px]", activeId === g ? "border-primary/60 bg-primary/15 text-foreground" : "border-border text-muted-foreground")}>
                    <span className="inline-block h-2 w-2 rounded-full mr-1 align-middle" style={{ background: g === "gateA" ? COLORS.gateA : COLORS.gateB }} />
                    {g === "gateA" ? "Gate A" : "Gate B"} ({g === "gateA" ? gateA.length : gateB.length} pts)
                  </button>
                ))}
              </div>
              <PointList points={activeId === "gateB" ? gateB : gateA} onChange={(p) => onShapeChange(activeId === "gateB" ? "gateB" : "gateA", p)} color={activeId === "gateB" ? COLORS.gateB : COLORS.gateA} />
              <div className="grid grid-cols-2 gap-2">
                <label className="space-y-1 text-muted-foreground">Distance A→B (m)
                  <input type="number" min={0.5} step={0.5} value={distance} onChange={(e) => setDistance(e.target.value)} className={inputCls} />
                </label>
                <label className="space-y-1 text-muted-foreground">Posted speed (km/h)
                  <input type="number" min={5} step={5} value={posted} onChange={(e) => setPosted(e.target.value)} className={inputCls} />
                </label>
              </div>
              <button onClick={saveSpeed} disabled={speedSaving} className={btnPrimary}>{speedSaving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />} Save calibration</button>
              {speedMsg && <StatusMsg kind={speedMsg.kind} text={speedMsg.text} />}
            </>
          )}

          {mode === "moving" && (
            <>
              <p className="text-muted-foreground">Optional polygon restricting Moving Object reports to a region. Stored as the <code>zone</code> parameter of the moving_object binding — save with <b>Save bindings</b> above.</p>
              {!movingEnabled && <StatusMsg kind="warn" text="Moving Object pack is not enabled for this camera; enable it above so the zone is saved with its binding." />}
              <PointList points={movingZone} onChange={setMovingZone} color={COLORS.moving} />
            </>
          )}

          {mode === "count" && (
            <>
              <p className="text-muted-foreground">Exactly two points, drawn <b>A → B</b> across the lane. Vehicles crossing it are counted by class and direction. Stored as the <code>count_line</code> parameter of the vehicle_count binding — save with <b>Save bindings</b> above.</p>
              {!countEnabled && <StatusMsg kind="warn" text="Vehicle Count pack is not enabled for this camera; enable it above so the line is saved with its binding." />}
              {countEnabled && count.count_line.length < 2 && <StatusMsg kind="warn" text="Place two points (A then B) — the binding cannot be saved without them." />}
              <PointList points={count.count_line} onChange={(p) => onShapeChange("count", p)} color={COLORS.count} />
              <div className="grid grid-cols-2 gap-2">
                <label className="space-y-1 text-muted-foreground">Label A → B
                  <input value={count.label_a_to_b} onChange={(e) => setCount({ ...count, label_a_to_b: e.target.value })} className={inputCls} placeholder="northbound" />
                </label>
                <label className="space-y-1 text-muted-foreground">Label B → A
                  <input value={count.label_b_to_a} onChange={(e) => setCount({ ...count, label_b_to_a: e.target.value })} className={inputCls} placeholder="southbound" />
                </label>
              </div>
              <div className="space-y-1 text-muted-foreground">
                <p>Classes counted</p>
                <div className="flex items-center gap-3 flex-wrap">
                  {COUNT_CLASSES.map((c) => (
                    <label key={c} className="flex items-center gap-1.5">
                      <input type="checkbox" checked={count.classes.includes(c)} className="rounded border-input bg-background"
                        onChange={(e) => setCount({ ...count, classes: e.target.checked ? [...count.classes.filter((x) => x !== c), c] : count.classes.filter((x) => x !== c) })} /> {c}
                    </label>
                  ))}
                </div>
              </div>
              <label className="block space-y-1 text-muted-foreground">Min observations before counting
                <input type="number" min={1} value={count.min_observations} onChange={(e) => setCount({ ...count, min_observations: Math.max(1, parseInt(e.target.value) || 1) })} className={cn(inputCls, "w-24")} />
              </label>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function UseCaseStudio() {
  const [params, setParams] = useSearchParams();
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [packs, setPacks] = useState<UseCasePack[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const selectedId = params.get("camera_id");
  const [movingZone, setMovingZone] = useState<Point[]>([]);
  const [movingEnabled, setMovingEnabled] = useState(false);
  const [count, setCount] = useState<CountConfig>(DEFAULT_COUNT);
  const [countEnabled, setCountEnabled] = useState(false);

  useEffect(() => {
    Promise.all([api.cameras.list(), api.useCases.list()])
      .then(([cams, ps]) => {
        setCameras(cams); setPacks(ps);
        if (cams.length > 0 && (!selectedId || !cams.some((c) => c.id === selectedId))) setParams({ camera_id: cams[0].id }, { replace: true });
      })
      .catch((e) => setError(apiErrorMessage(e, "Could not load cameras")))
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const selected = cameras.find((c) => c.id === selectedId) ?? null;

  /** Server-confirmed bindings: seed the drawn moving-object zone from the saved parameter. */
  function onBindingsLoaded(b: UiBinding[]) {
    const moving = b.find((x) => x.pack_id === "moving_object" && x.enabled);
    setMovingEnabled(Boolean(moving));
    const zone = moving?.parameters?.zone;
    setMovingZone(Array.isArray(zone) ? (zone as Point[]) : []);
    const vc = b.find((x) => x.pack_id === "vehicle_count" && x.enabled);
    setCountEnabled(Boolean(vc));
    if (vc) setCount(countFromParams(vc.parameters));
  }
  function onBindingsChange(b: UiBinding[]) {
    setMovingEnabled(b.some((x) => x.pack_id === "moving_object" && x.enabled));
    setCountEnabled(b.some((x) => x.pack_id === "vehicle_count" && x.enabled));
  }

  useEffect(() => { setMovingZone([]); setMovingEnabled(false); setCount(DEFAULT_COUNT); setCountEnabled(false); }, [selectedId]);

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-lg font-semibold">Use-case Studio</h1>
        <div className="flex items-center gap-2">
          <label className="text-xs text-muted-foreground">Camera</label>
          <select value={selectedId ?? ""} onChange={(e) => setParams({ camera_id: e.target.value })} className={cn(selectCls, "w-auto min-w-[200px]")}>
            {cameras.map((c) => <option key={c.id} value={c.id}>{c.name}{c.enabled ? "" : " (disabled)"}</option>)}
          </select>
          {selected && <ProfileChip profile={selected.profile} />}
          {selected && <CameraStateChip state={selected.enabled ? selected.runtime?.state : "stopped"} />}
        </div>
      </div>

      {error && <StatusMsg kind="err" text={error} />}
      {loading && <p className="text-sm text-muted-foreground">Loading…</p>}

      {!loading && cameras.length === 0 && (
        <div className="rounded-lg border border-dashed border-border bg-card/50 px-4 py-8 text-center text-sm text-muted-foreground">
          No cameras yet. Add one on the <Link to="/cameras" className="text-primary underline underline-offset-2">Cameras</Link> page first.
        </div>
      )}

      {selected && (
        <div className="space-y-3">
          <Section title="Use-case packs" badge={<span className="text-[10px] text-muted-foreground font-normal">bindings apply live</span>}>
            <BindingsSection key={selected.id} cameraId={selected.id} packs={packs} movingZone={movingZone} count={count} onLoaded={onBindingsLoaded} onChange={onBindingsChange} />
          </Section>
          <Section title="Zone editor" badge={<span className="text-[10px] text-muted-foreground font-normal">stop zone · speed gates · moving-object zone · count line</span>}>
            <ZoneEditorSection key={selected.id} cameraId={selected.id} movingZone={movingZone} setMovingZone={setMovingZone} movingEnabled={movingEnabled} count={count} setCount={setCount} countEnabled={countEnabled} />
          </Section>
        </div>
      )}
    </div>
  );
}
