const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    const err = new ApiError(res.status, detail);
    throw err;
  }
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    public detail: any
  ) {
    super(`API ${status}`);
  }
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Camera {
  id: string;
  name: string;
  profile: string;
  rtsp_url: string;
  detection_adapter: string;
  enabled: boolean;
  last_frame_at?: string;
}

export interface Binding {
  pack_id: string;
  parameters: Record<string, unknown>;
  report_interval_seconds: number;
  enabled: boolean;
}

export interface UseCasePack {
  pack_id: string;
  version: string;
  requires: string[];
  parameters_schema: Record<string, unknown>;
}

export interface TrafficEvent {
  event_id: string;
  camera_id: string;
  event_type: string;
  severity: string;
  confidence: number;
  timestamp: string;
  metadata: Record<string, unknown>;
  [key: string]: unknown;
}

export interface Incident {
  incident_id: string;
  camera_id: string;
  severity: string;
  status: string;
  created_at: string;
  events: TrafficEvent[];
  notes: string;
}

export interface KpiTile {
  key: string;
  label: string;
  value: number | string | null;
  unit?: string;
  data_source: "mock" | "live-rtsp" | "validated-benchmark";
  tooltip?: string;
}

export interface KpisResponse {
  tiles: KpiTile[];
  adapter: string;
}

export interface FlowResponse {
  window_start: string;
  window_end: string;
  vehicle_count: number;
  person_count: number;
  congestion_windows: number;
  class_counts: Record<string, number>;
  data_source: "mock" | "live-rtsp" | "validated-benchmark";
  tooltip?: string;
}

export interface ArtifactEntry {
  path: string;
  kind: string;
  size_bytes: number;
  last_modified: string;
}

export interface SpeedCalibration {
  camera_id: string;
  gate_a: number[][];
  gate_b: number[][];
  real_world_distance_m: number;
  captured_at: string;
}

// ── API calls ─────────────────────────────────────────────────────────────────

export const api = {
  cameras: {
    list: () => get<Camera[]>("/cameras"),
    bindings: (id: string) => get<Binding[]>(`/cameras/${id}/bindings`),
    putBindings: (id: string, bindings: Binding[]) =>
      put<Binding[]>(`/cameras/${id}/bindings`, bindings),
    speedCalibration: (id: string) =>
      get<SpeedCalibration>(`/cameras/${id}/speed-calibration`),
    putSpeedCalibration: (id: string, cal: Partial<SpeedCalibration>) =>
      post<SpeedCalibration>(`/cameras/${id}/speed-calibration`, cal),
    stopZone: (id: string) =>
      get<Record<string, unknown>>(`/cameras/${id}/stop-zone`),
    putStopZone: (id: string, zone: Record<string, unknown>) =>
      put<Record<string, unknown>>(`/cameras/${id}/stop-zone`, zone),
  },
  useCases: {
    list: () => get<UseCasePack[]>("/use-cases"),
  },
  events: {
    list: (params?: { camera_id?: string; cursor?: string; limit?: number }) => {
      const qs = new URLSearchParams();
      if (params?.camera_id) qs.set("camera_id", params.camera_id);
      if (params?.cursor) qs.set("cursor", params.cursor);
      if (params?.limit) qs.set("limit", String(params.limit));
      const q = qs.toString();
      return get<TrafficEvent[]>(`/events${q ? `?${q}` : ""}`);
    },
  },
  incidents: {
    list: (status?: string) =>
      get<Incident[]>(`/incidents${status ? `?status=${status}` : ""}`),
    get: (id: string) => get<Incident>(`/incidents/${id}`),
    transition: (id: string, action: string, note?: string) =>
      post<Incident>(`/incidents/${id}/transition`, { action, note: note ?? "" }),
  },
  metrics: {
    kpis: () => get<KpisResponse>("/metrics/kpis"),
    flow: () => get<FlowResponse>("/metrics/flow"),
    inference: () => get<Record<string, unknown>>("/metrics/inference"),
  },
  artifacts: {
    list: () => get<ArtifactEntry[]>("/artifacts"),
    get: (path: string) => get<unknown>(`/artifacts/${encodeURIComponent(path)}`),
  },
  runtime: () => get<Record<string, unknown>>("/runtime"),
  snapshotUrl: (cameraId: string) =>
    `${BASE}/stream/${cameraId}/snapshot.jpg?t=${Date.now()}`,
};
