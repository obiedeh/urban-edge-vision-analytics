import { useState } from "react";
import { AlertTriangle, X } from "lucide-react";

interface Props {
  dismissible?: boolean;
}

export function CredibilityBanner({ dismissible = true }: Props) {
  const [dismissed, setDismissed] = useState(false);
  if (dismissed) return null;

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
          onClick={() => setDismissed(true)}
          className="text-yellow-400 hover:text-yellow-200"
          aria-label="Dismiss"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
