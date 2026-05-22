import { useEffect, useState } from "react";
import { api, type ArtifactEntry } from "@/lib/api";
import { FileText, FolderOpen, ChevronRight, X } from "lucide-react";
import { cn } from "@/lib/utils";

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function kindIcon(kind: string) {
  if (kind === "directory") return <FolderOpen className="h-4 w-4 text-yellow-400 shrink-0" />;
  return <FileText className="h-4 w-4 text-blue-400 shrink-0" />;
}

function extOf(path: string): string {
  const parts = path.split(".");
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : "";
}

// ── JSON / text viewer ────────────────────────────────────────────────────────

function ArtifactViewer({
  entry,
  onClose,
}: {
  entry: ArtifactEntry;
  onClose: () => void;
}) {
  const [content, setContent] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.artifacts
      .get(entry.path)
      .then(setContent)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [entry.path]);

  const ext = extOf(entry.path);
  const isJson = ext === "json" || ext === "jsonl";

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-[640px] max-w-full bg-card border-l border-border flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-4 py-3 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            {kindIcon(entry.kind)}
            <span className="text-sm font-medium text-foreground truncate">{entry.path}</span>
          </div>
          <button onClick={onClose} className="ml-2 text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Meta strip */}
        <div className="flex gap-4 border-b border-border px-4 py-2 text-[10px] text-muted-foreground shrink-0">
          <span>{fmtSize(entry.size_bytes)}</span>
          <span>{fmtDate(entry.last_modified)}</span>
          <span className="ml-auto uppercase tracking-wide">{entry.kind}</span>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4">
          {loading && (
            <p className="text-sm text-muted-foreground">Loading…</p>
          )}
          {error && (
            <p className="text-sm text-red-400">{error}</p>
          )}
          {!loading && !error && content !== null && (
            <pre className="text-[11px] text-foreground/90 whitespace-pre-wrap font-mono leading-relaxed">
              {isJson
                ? JSON.stringify(content, null, 2)
                : String(content)}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}

// ── File tree ─────────────────────────────────────────────────────────────────

function groupByDir(entries: ArtifactEntry[]): Map<string, ArtifactEntry[]> {
  const map = new Map<string, ArtifactEntry[]>();
  for (const e of entries) {
    const slash = e.path.lastIndexOf("/");
    const dir = slash === -1 ? "" : e.path.slice(0, slash);
    if (!map.has(dir)) map.set(dir, []);
    map.get(dir)!.push(e);
  }
  return map;
}

function FileRow({
  entry,
  onClick,
}: {
  entry: ArtifactEntry;
  onClick: (e: ArtifactEntry) => void;
}) {
  const name = entry.path.split("/").pop() ?? entry.path;
  const isDir = entry.kind === "directory";
  return (
    <button
      onClick={() => !isDir && onClick(entry)}
      disabled={isDir}
      className={cn(
        "w-full flex items-center gap-2 rounded px-3 py-2 text-sm text-left transition-colors",
        isDir
          ? "text-muted-foreground cursor-default"
          : "text-foreground hover:bg-secondary cursor-pointer"
      )}
    >
      {kindIcon(entry.kind)}
      <span className="flex-1 font-mono text-xs truncate">{name}</span>
      <span className="text-[10px] text-muted-foreground shrink-0">{fmtSize(entry.size_bytes)}</span>
      {!isDir && <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0" />}
    </button>
  );
}

function DirGroup({
  dir,
  entries,
  onSelect,
}: {
  dir: string;
  entries: ArtifactEntry[];
  onSelect: (e: ArtifactEntry) => void;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground bg-secondary/20 border-b border-border"
      >
        <FolderOpen className="h-3.5 w-3.5 text-yellow-400" />
        <span className="flex-1 text-left font-mono">{dir || "/"}</span>
        <span>{entries.length} file{entries.length !== 1 ? "s" : ""}</span>
      </button>
      {open && (
        <div className="divide-y divide-border">
          {entries.map((e) => (
            <FileRow key={e.path} entry={e} onClick={onSelect} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Root page ─────────────────────────────────────────────────────────────────

export function ArtifactsPage() {
  const [entries, setEntries] = useState<ArtifactEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<ArtifactEntry | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    api.artifacts.list().then(setEntries).catch(() => null).finally(() => setLoading(false));
  }, []);

  const filtered = search
    ? entries.filter((e) => e.path.toLowerCase().includes(search.toLowerCase()))
    : entries;

  const grouped = groupByDir(filtered.filter((e) => e.kind !== "directory"));

  const totalSize = entries.reduce((s, e) => s + e.size_bytes, 0);

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-lg font-semibold">Evidence Artifacts</h1>
        <div className="flex items-center gap-3">
          <input
            type="text"
            placeholder="Filter…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="rounded border border-input bg-background px-2 py-1 text-xs text-foreground w-48"
          />
          <span className="text-xs text-muted-foreground">
            {entries.length} file{entries.length !== 1 ? "s" : ""} · {fmtSize(totalSize)}
          </span>
        </div>
      </div>

      {loading && (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-10 rounded snapshot-shimmer" />
          ))}
        </div>
      )}

      {!loading && entries.length === 0 && (
        <div className="py-12 text-center text-sm text-muted-foreground">
          No artifacts found. Run the detection pipeline to generate evidence files.
        </div>
      )}

      {!loading && filtered.length === 0 && entries.length > 0 && (
        <div className="py-12 text-center text-sm text-muted-foreground">
          No files match &ldquo;{search}&rdquo;.
        </div>
      )}

      {!loading && grouped.size > 0 && (
        <div className="space-y-3">
          {[...grouped.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([dir, files]) => (
            <DirGroup
              key={dir}
              dir={dir}
              entries={files}
              onSelect={setSelected}
            />
          ))}
        </div>
      )}

      {selected && (
        <ArtifactViewer entry={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
