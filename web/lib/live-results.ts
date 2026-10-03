import { useEffect, useRef, useState } from "react";
import { api, type InferenceResult } from "./api";

/**
 * Subscribe to GET /live/results (SSE, event name "inference_result").
 * Returns the latest result per camera; the server replays the last result on connect.
 * Pass a cameraId to restrict the subscription server-side.
 */
export function useLiveResults(cameraId?: string | null, enabled = true) {
  const [results, setResults] = useState<Record<string, InferenceResult>>({});
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!enabled) return;
    setResults({});
    const es = new EventSource(api.live.resultsUrl(cameraId ?? undefined));
    esRef.current = es;
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.addEventListener("inference_result", (message) => {
      try {
        const result = JSON.parse((message as MessageEvent).data as string) as InferenceResult;
        setResults((prev) => ({ ...prev, [result.camera_id]: result }));
      } catch {
        // malformed payload — the next result replaces it
      }
    });
    return () => {
      es.close();
      esRef.current = null;
      setConnected(false);
    };
  }, [cameraId, enabled]);

  return { results, connected };
}

/** Convenience: the latest result for a single camera. */
export function useLiveResult(cameraId: string | null | undefined) {
  const { results, connected } = useLiveResults(cameraId ?? undefined, Boolean(cameraId));
  return { result: cameraId ? results[cameraId] ?? null : null, connected };
}
