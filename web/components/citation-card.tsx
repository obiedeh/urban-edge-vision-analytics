import { DataSourceBadge, type DataSource } from "./data-source-badge";

interface Props {
  title: string;
  source: DataSource;
  tooltip?: string;
  children: React.ReactNode;
}

export function CitationCard({ title, source, tooltip, children }: Props) {
  return (
    <div className="rounded-lg border border-border bg-card p-4 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          {title}
        </span>
        <DataSourceBadge source={source} tooltip={tooltip} />
      </div>
      <div className="text-2xl font-bold text-foreground">{children}</div>
    </div>
  );
}
