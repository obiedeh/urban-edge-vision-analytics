import type { Detection, PackEventRef, Point } from "@/lib/api";

const LABEL_COLORS: Record<string, string> = {
  car: "#60a5fa",
  truck: "#f59e0b",
  bus: "#fb923c",
  motorcycle: "#a78bfa",
  bicycle: "#34d399",
  cyclist: "#34d399",
  pedestrian: "#f472b6",
  person: "#f472b6",
};

function colorFor(label: string): string {
  return LABEL_COLORS[label?.toLowerCase()] ?? "#e2e8f0";
}

interface Props {
  detections: Detection[];
  packEvents?: PackEventRef[];
  /** rendered video box size in CSS px */
  width: number;
  height: number;
  /** when the rendered <img>/<video> is object-contain, pass the intrinsic size to letterbox correctly */
  intrinsic?: { width: number; height: number } | null;
  stale?: boolean;
  /** vehicle_count binding's count_line (normalized A→B), drawn as a dashed amber line */
  countLine?: Point[] | null;
}

/**
 * SVG overlay drawing normalized (0..1) bounding boxes on top of a video element.
 * Track ids referenced by pack events are highlighted in red.
 */
export function DetectionOverlay({ detections, packEvents = [], width, height, intrinsic, stale, countLine }: Props) {
  if (width <= 0 || height <= 0) return null;

  // Account for object-contain letterboxing.
  let drawW = width, drawH = height, offX = 0, offY = 0;
  if (intrinsic && intrinsic.width > 0 && intrinsic.height > 0) {
    const scale = Math.min(width / intrinsic.width, height / intrinsic.height);
    drawW = intrinsic.width * scale;
    drawH = intrinsic.height * scale;
    offX = (width - drawW) / 2;
    offY = (height - drawH) / 2;
  }

  // Pack events do not carry track ids, so when a pack fired on this frame every
  // tracked box is tinted red and the event banner names the pack/type.
  const hasPackEvent = packEvents.some((pe) => pe.event_type !== "scene_clear");

  return (
    <svg
      className="absolute inset-0 pointer-events-none"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      style={{ opacity: stale ? 0.45 : 1, transition: "opacity 300ms" }}
    >
      {countLine && countLine.length >= 2 && (() => {
        const [ax, ay] = [offX + countLine[0][0] * drawW, offY + countLine[0][1] * drawH];
        const [bx, by] = [offX + countLine[1][0] * drawW, offY + countLine[1][1] * drawH];
        return (
          <g fontFamily="ui-monospace, monospace" fontSize={11} fontWeight={700}>
            <line x1={ax} y1={ay} x2={bx} y2={by} stroke="#fbbf24" strokeWidth={2} strokeDasharray="6 4" />
            <circle cx={ax} cy={ay} r={4} fill="#fbbf24" /><circle cx={bx} cy={by} r={4} fill="#fbbf24" />
            <text x={ax + 7} y={ay - 6} fill="#fbbf24" stroke="#0b1220" strokeWidth={3} paintOrder="stroke">A</text>
            <text x={bx + 7} y={by - 6} fill="#fbbf24" stroke="#0b1220" strokeWidth={3} paintOrder="stroke">B</text>
          </g>
        );
      })()}
      {detections.map((d, i) => {
        const [nx, ny, nw, nh] = d.bbox;
        const x = offX + nx * drawW;
        const y = offY + ny * drawH;
        const w = Math.max(2, nw * drawW);
        const h = Math.max(2, nh * drawH);
        const color = colorFor(d.label);
        const hot = hasPackEvent && d.track_id != null;
        const stroke = hot ? "#ef4444" : color;
        const label = `${d.label}${d.track_id ? ` #${d.track_id}` : ""} ${(d.confidence * 100).toFixed(0)}%`;
        const fontSize = 11;
        const labelW = label.length * (fontSize * 0.6) + 8;
        const labelY = y - 16 < 0 ? y + h : y - 16;
        return (
          <g key={`${d.track_id ?? "d"}-${i}`}>
            <rect x={x} y={y} width={w} height={h} fill={stroke} fillOpacity={hot ? 0.18 : 0.08} stroke={stroke} strokeWidth={hot ? 2.5 : 1.5} rx={2} />
            <rect x={x} y={labelY} width={labelW} height={16} fill="rgba(2,6,23,0.85)" stroke={stroke} strokeWidth={0.75} rx={2} />
            <text x={x + 4} y={labelY + 12} fontSize={fontSize} fontFamily="ui-monospace, monospace" fill={stroke}>
              {label}
            </text>
          </g>
        );
      })}
      {packEvents.length > 0 && (
        <g>
          {packEvents.map((pe, i) => (
            <g key={pe.event_id || i} transform={`translate(${offX + 8}, ${offY + 8 + i * 20})`}>
              <rect width={Math.max(120, pe.event_type.length * 7 + 60)} height={16} fill="rgba(239,68,68,0.9)" rx={3} />
              <text x={6} y={12} fontSize={10} fontFamily="ui-monospace, monospace" fill="#fff" fontWeight={700}>
                {pe.pack_id} · {pe.event_type} · {pe.severity}
              </text>
            </g>
          ))}
        </g>
      )}
    </svg>
  );
}
