import { useEffect, useRef, useState } from "react";
import type { TrafficEvent } from "./api";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export function useEventStream(maxEvents = 100) {
  const [events, setEvents] = useState<TrafficEvent[]>([]);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const es = new EventSource(`${BASE}/events/sse`);
    esRef.current = es;

    es.onmessage = (e: MessageEvent) => {
      try {
        const evt = JSON.parse(e.data as string) as TrafficEvent;
        setEvents((prev) => [evt, ...prev].slice(0, maxEvents));
      } catch {
        // ignore malformed messages
      }
    };

    return () => {
      es.close();
    };
  }, [maxEvents]);

  return events;
}
