import { useState } from "react";
import { AlertTriangle, X } from "lucide-react";

const STORAGE_KEY = "credibility_banner_dismissed";

interface Props {
  dismissible?: boolean;
}

export function CredibilityBanner({ dismissible = true }: Props) {
  // Initialise from localStorage so dismissal survives page navigations
  const [dismissed, setDismissed] = useState<boolean>(
    () => {
      try {
        return localStorage.getItem(STORAGE_KEY) === "1";
      } catch {
        return false; // SSR / privacy-mode guard
      }
    }
  );

  if (dismissed) return null;

  function dismiss() {
    try {
      localStorage.setItem(STORAGE_KEY, "1");
    } catch {
      // ignore write failures (private browsing, quota)
    }
    setDismissed(true);
  }

  return (
    <div className="flex items-start gap-3 px-4 py-3 bg-yellow-500/10 border border-yellow-500/30 rounded-md text-sm text-yellow-300">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-yellow-400" />
      <span className="flex-1">
        <strong className="font-semibold">Mock adapter active.</strong>{" "}
        Mock adapter — does not prove real camera accuracy, Jetson latency,
        TensorRT acceleration, or automated enforcement readiness.
      </span>
      {dismissible && (
        <button
          onClick={dismiss}
          className="text-yellow-400 hover:text-yellow-200 shrink-0"
          aria-label="Dismiss"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
