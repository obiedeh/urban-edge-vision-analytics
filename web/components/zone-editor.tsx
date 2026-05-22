/**
 * Minimal polygon zone editor — click to add points, close to finish.
 * MVP: renders a plain coordinate list; visual canvas editor is Future Scope.
 */
import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface Point {
  x: number;
  y: number;
}

interface Props {
  label: string;
  points: Point[];
  onChange: (pts: Point[]) => void;
  className?: string;
}

export function ZoneEditor({ label, points, onChange, className }: Props) {
  const [xInput, setXInput] = useState("");
  const [yInput, setYInput] = useState("");

  function addPoint() {
    const x = parseFloat(xInput);
    const y = parseFloat(yInput);
    if (isNaN(x) || isNaN(y)) return;
    onChange([...points, { x, y }]);
    setXInput("");
    setYInput("");
  }

  return (
    <div className={cn("space-y-2", className)}>
      <p className="text-sm font-medium text-foreground">{label}</p>
      <div className="rounded border border-border bg-muted/20 p-2 space-y-1 min-h-[60px]">
        {points.length === 0 && (
          <p className="text-xs text-muted-foreground">No points defined.</p>
        )}
        {points.map((pt, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground w-5">{i + 1}.</span>
            <span className="font-mono text-foreground">
              ({pt.x}, {pt.y})
            </span>
            <button
              onClick={() => onChange(points.filter((_, j) => j !== i))}
              className="ml-auto text-destructive hover:text-destructive/80"
            >
              <Trash2 className="h-3 w-3" />
            </button>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          type="number"
          placeholder="x"
          value={xInput}
          onChange={(e) => setXInput(e.target.value)}
          className="w-20 rounded border border-input bg-background px-2 py-1 text-xs text-foreground"
        />
        <input
          type="number"
          placeholder="y"
          value={yInput}
          onChange={(e) => setYInput(e.target.value)}
          className="w-20 rounded border border-input bg-background px-2 py-1 text-xs text-foreground"
        />
        <button
          onClick={addPoint}
          className="flex items-center gap-1 rounded bg-primary/20 px-2 py-1 text-xs text-primary hover:bg-primary/30"
        >
          <Plus className="h-3 w-3" /> Add point
        </button>
      </div>
    </div>
  );
}
