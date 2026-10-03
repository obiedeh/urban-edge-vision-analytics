import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Point } from "@/lib/api";
import { cn, btnGhost } from "@/lib/utils";
import { RefreshCw, Trash2, Undo2, ImageOff } from "lucide-react";

export interface Shape {
  id: string;
  label: string;
  points: Point[];
  color: string;
  /** "polygon" closes the path; "line" draws a polyline (2 points = gate line) */
  kind?: "polygon" | "line";
}

interface Props {
  cameraId: string;
  shapes: Shape[];
  /** id of the shape receiving clicks; null = read-only */
  activeId: string | null;
  onChange: (id: string, points: Point[]) => void;
  className?: string;
}

const HANDLE_R = 6;

/**
 * Draw normalized (0..1) polygons/lines on a camera snapshot.
 * - click: add a vertex to the active shape
 * - drag a vertex: move it
 * - right-click / Backspace / Delete: remove the last vertex of the active shape
 * Coordinates are stored normalized by dividing by the rendered image size, so
 * they are independent of the frame resolution.
 */
export function ZoneCanvas({ cameraId, shapes, activeId, onChange, className }: Props) {
  const boxRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [intrinsic, setIntrinsic] = useState<{ width: number; height: number } | null>(null);
  const [src, setSrc] = useState(() => api.stream.snapshotUrl(cameraId));
  const [imgErr, setImgErr] = useState(false);
  const [drag, setDrag] = useState<{ shapeId: string; index: number } | null>(null);

  const refresh = useCallback(() => { setImgErr(false); setSrc(api.stream.snapshotUrl(cameraId)); }, [cameraId]);
  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const r = entries[0]?.contentRect;
      if (r) setSize({ width: r.width, height: r.height });
    });
    ro.observe(el);
    setSize({ width: el.clientWidth, height: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  // Letterbox geometry for object-contain.
  let drawW = size.width, drawH = size.height, offX = 0, offY = 0;
  if (intrinsic && intrinsic.width > 0) {
    const scale = Math.min(size.width / intrinsic.width, size.height / intrinsic.height);
    drawW = intrinsic.width * scale; drawH = intrinsic.height * scale;
    offX = (size.width - drawW) / 2; offY = (size.height - drawH) / 2;
  }
  const toPx = ([nx, ny]: Point): [number, number] => [offX + nx * drawW, offY + ny * drawH];
  const toNorm = (px: number, py: number): Point => [
    Math.min(1, Math.max(0, (px - offX) / (drawW || 1))),
    Math.min(1, Math.max(0, (py - offY) / (drawH || 1))),
  ];

  function localPoint(e: React.MouseEvent): [number, number] {
    const rect = boxRef.current!.getBoundingClientRect();
    return [e.clientX - rect.left, e.clientY - rect.top];
  }

  const active = shapes.find((s) => s.id === activeId) ?? null;

  function handleClick(e: React.MouseEvent) {
    if (!active || drag) return;
    const [px, py] = localPoint(e);
    const p = toNorm(px, py);
    onChange(active.id, [...active.points, [Number(p[0].toFixed(4)), Number(p[1].toFixed(4))]]);
  }

  function removeLast() {
    if (!active || active.points.length === 0) return;
    onChange(active.id, active.points.slice(0, -1));
  }

  function handleContextMenu(e: React.MouseEvent) {
    e.preventDefault();
    removeLast();
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!active) return;
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT")) return;
      if (e.key === "Backspace" || e.key === "Delete") { e.preventDefault(); removeLast(); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.id, active?.points.length]);

  function handleMove(e: React.MouseEvent) {
    if (!drag) return;
    const shape = shapes.find((s) => s.id === drag.shapeId);
    if (!shape) return;
    const [px, py] = localPoint(e);
    const p = toNorm(px, py);
    const pts = shape.points.slice();
    pts[drag.index] = [Number(p[0].toFixed(4)), Number(p[1].toFixed(4))];
    onChange(shape.id, pts);
  }

  const endDrag = () => {
    // Defer so the click handler that follows mouseup sees `drag` still set and skips adding a vertex.
    if (drag) setTimeout(() => setDrag(null), 0);
  };

  return (
    <div className={cn("space-y-2", className)}>
      <div
        ref={boxRef}
        className={cn("relative w-full aspect-video bg-black rounded border border-border overflow-hidden select-none", active ? "cursor-crosshair" : "cursor-default")}
        onClick={handleClick}
        onContextMenu={handleContextMenu}
        onMouseMove={handleMove}
        onMouseUp={endDrag}
        onMouseLeave={endDrag}
      >
        <img
          src={src}
          alt="camera frame"
          draggable={false}
          className="absolute inset-0 w-full h-full object-contain pointer-events-none"
          onLoad={(e) => {
            const im = e.currentTarget;
            if (im.naturalWidth) setIntrinsic((prev) => (prev && prev.width === im.naturalWidth && prev.height === im.naturalHeight ? prev : { width: im.naturalWidth, height: im.naturalHeight }));
            setImgErr(false);
          }}
          onError={() => setImgErr(true)}
        />
        {imgErr && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-muted-foreground text-xs pointer-events-none">
            <ImageOff className="h-5 w-5" />
            No frame available — camera not running? You can still draw on the blank canvas.
          </div>
        )}
        {size.width > 0 && (
          <svg className="absolute inset-0" width={size.width} height={size.height}>
            {/* letterbox outline of the frame */}
            {intrinsic && <rect x={offX} y={offY} width={drawW} height={drawH} fill="none" stroke="rgba(255,255,255,0.15)" strokeDasharray="4 4" />}
            {shapes.map((s) => {
              if (s.points.length === 0) return null;
              const px = s.points.map(toPx);
              const d = px.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x},${y}`).join(" ");
              const isActive = s.id === activeId;
              const closed = (s.kind ?? "polygon") === "polygon" && s.points.length >= 3;
              return (
                <g key={s.id} opacity={activeId && !isActive ? 0.55 : 1}>
                  <path d={closed ? `${d} Z` : d} fill={closed ? s.color : "none"} fillOpacity={0.18} stroke={s.color} strokeWidth={isActive ? 2.5 : 1.5} />
                  {px.map(([x, y], i) => (
                    <circle
                      key={i}
                      cx={x} cy={y} r={isActive ? HANDLE_R : HANDLE_R - 2}
                      fill={s.color} stroke="#0b1220" strokeWidth={1.5}
                      className={isActive ? "cursor-move" : undefined}
                      style={{ pointerEvents: isActive ? "auto" : "none" }}
                      onMouseDown={(e) => { e.stopPropagation(); e.preventDefault(); setDrag({ shapeId: s.id, index: i }); }}
                    />
                  ))}
                  <text x={px[0][0] + 8} y={px[0][1] - 8} fontSize={11} fontFamily="ui-monospace, monospace" fill={s.color} fontWeight={700}>{s.label}</text>
                </g>
              );
            })}
          </svg>
        )}
      </div>
      <div className="flex items-center gap-2 flex-wrap text-[10px] text-muted-foreground">
        <button type="button" onClick={refresh} className={cn(btnGhost, "py-1")}><RefreshCw className="h-3 w-3" /> Refresh frame</button>
        <button type="button" onClick={removeLast} disabled={!active || active.points.length === 0} className={cn(btnGhost, "py-1")}><Undo2 className="h-3 w-3" /> Remove last</button>
        <button type="button" onClick={() => active && onChange(active.id, [])} disabled={!active || active.points.length === 0} className={cn(btnGhost, "py-1 text-red-400/80 hover:text-red-400")}><Trash2 className="h-3 w-3" /> Clear</button>
        <span className="ml-auto">
          {active ? <>Drawing <span className="font-semibold" style={{ color: active.color }}>{active.label}</span> — click to add, drag to move, right-click/Backspace to undo</> : "Select a shape to edit"}
        </span>
      </div>
    </div>
  );
}

/** Numeric fallback list for a shape's vertices (normalized 0..1). */
export function PointList({ points, onChange, color }: { points: Point[]; onChange: (pts: Point[]) => void; color?: string }) {
  const [xi, setXi] = useState("");
  const [yi, setYi] = useState("");
  function add() {
    const x = parseFloat(xi), y = parseFloat(yi);
    if (isNaN(x) || isNaN(y)) return;
    onChange([...points, [Math.min(1, Math.max(0, x)), Math.min(1, Math.max(0, y))]]);
    setXi(""); setYi("");
  }
  const cell = "w-20 rounded border border-input bg-background px-1.5 py-0.5 text-[11px] font-mono text-foreground";
  return (
    <div className="rounded border border-border bg-muted/20 p-2 space-y-1">
      {points.length === 0 && <p className="text-[11px] text-muted-foreground">No points.</p>}
      {points.map((pt, i) => (
        <div key={i} className="flex items-center gap-2 text-[11px]">
          <span className="w-4 text-muted-foreground" style={{ color }}>{i + 1}</span>
          <input type="number" step={0.001} min={0} max={1} value={pt[0]} onChange={(e) => { const v = parseFloat(e.target.value); if (!isNaN(v)) { const n = points.slice(); n[i] = [v, pt[1]]; onChange(n); } }} className={cell} />
          <input type="number" step={0.001} min={0} max={1} value={pt[1]} onChange={(e) => { const v = parseFloat(e.target.value); if (!isNaN(v)) { const n = points.slice(); n[i] = [pt[0], v]; onChange(n); } }} className={cell} />
          <button type="button" onClick={() => onChange(points.filter((_, j) => j !== i))} className="ml-auto text-red-400/70 hover:text-red-400" aria-label="remove point"><Trash2 className="h-3 w-3" /></button>
        </div>
      ))}
      <div className="flex items-center gap-2 pt-1">
        <input type="number" step={0.001} min={0} max={1} placeholder="x" value={xi} onChange={(e) => setXi(e.target.value)} className={cell} />
        <input type="number" step={0.001} min={0} max={1} placeholder="y" value={yi} onChange={(e) => setYi(e.target.value)} className={cell} />
        <button type="button" onClick={add} className="text-[11px] text-primary hover:underline">Add point</button>
      </div>
    </div>
  );
}
