import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";
import {
  Camera, Activity, LayoutGrid, Settings, BarChart2, FolderOpen, Video, Cpu, ClipboardCheck,
} from "lucide-react";

const links = [
  { to: "/live",      label: "Live",      icon: Video },
  { to: "/cameras",   label: "Cameras",   icon: Camera },
  { to: "/models",    label: "Models",    icon: Cpu },
  { to: "/studio",    label: "Studio",    icon: Settings },
  { to: "/events",    label: "Events",    icon: Activity },
  { to: "/review",    label: "Review",    icon: ClipboardCheck },
  { to: "/metrics",   label: "Metrics",   icon: BarChart2 },
  { to: "/artifacts", label: "Artifacts", icon: FolderOpen },
];

export function NavBar() {
  return (
    <header className="border-b border-border bg-card px-4 py-2 flex items-center gap-6 flex-wrap">
      <div className="flex items-center gap-2 mr-4">
        <LayoutGrid className="h-5 w-5 text-primary" />
        <span className="font-semibold text-foreground text-sm tracking-tight">
          Urban Edge Vision
        </span>
      </div>
      <nav className="flex items-center gap-1 flex-wrap">
        {links.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors",
                isActive
                  ? "bg-primary/15 text-primary font-medium"
                  : "text-muted-foreground hover:text-foreground hover:bg-secondary"
              )
            }
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </NavLink>
        ))}
      </nav>
    </header>
  );
}
