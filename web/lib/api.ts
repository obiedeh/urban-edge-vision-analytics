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

async function del(path: string): Promise<void> {
  const res = await fetch(`${BASE}${path}`, { method: "DELETE" });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new ApiError(res.status, detail);
  }
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
  synthetic: boolean;
  enabled: boolean;
  last_frame_at?: string;
}

export interface CameraConfigPayload {
  camera_id?: string;
  model_type: string;
  host: string;
  port: number;
  stream: string;
  channel: number;
  username: string;
  password: string;
  rtsp_transport: string;
  detection_adapter: string;
  nvidia_endpoint?: string;
  nvidia_api_key?: string;
  synthetic?: boolean;
}

export interface CameraConfigResponse {
  camera_id: string;
  model_type: string;
  host: string;
  port: number;
  stream: string;
  channel: number;
  username: string;
  /** Always "••••••••" when returned from server */
  password: string;
  rtsp_transport: string;
  detection_adapter?: string;
  nvidia_endpoint?: string;
  nvidia_api_key?: string;
  synthetic?: boolean;
  status?: string;
}

export interface PipelineStatus {
  state: "running" | "stopped" | "failed" | "completed";
  pid: number | null;
  uptime_seconds: number | null;
  camera_id: string | null;
  adapter: string | null;
  synthetic: boolean | null;
  config_path?: string;
  exit_code?: number;
  log_tail: string[];
}

export interface CameraTestResponse {
  ok: boolean;
  camera_id: string;
  masked_url?: string;
  reachable?: boolean;
  reach_error?: string | null;
  error?: string;
  stage: string;
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

export interface OllamaModel {
  name: string;
  size_gb?: number;
  family?: string;
  parameter_size?: string;
  vision: boolean;
  // catalog extras (may be absent for models not in catalog)
  label?: string;
  tier?: "nano" | "mid" | "high" | "max";
  vram_gb?: number;
  description?: string;
  tags?: string[];
}

export interface CatalogModel {
  name: string;
  hf_id: string;
  label: string;
  family: string;
  vision: boolean;
  params_b: number;
  vram_gb: number;
  tier: "nano" | "mid" | "high" | "max";
  backend: "ollama" | "vllm";
  description: string;
  pull_cmd: string;
  tags: string[];
  installed: boolean;
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
    getConfig: () => get<CameraConfigResponse>("/cameras/config"),
    saveConfig: (payload: CameraConfigPayload) =>
      post<CameraConfigResponse>("/cameras/config", payload),
    testConfig: (payload: CameraConfigPayload) =>
      post<CameraTestResponse>("/cameras/config/test", payload),
    deleteConfig: () => del("/cameras/config"),
    bindings: (id: string) => get<Binding[]>(`/cameras/${id}/bindings`),
    putBindings: (id: string, bindings: Binding[]) =>
      put<{ camera_id: string; bindings: number; status: string }>(
        `/cameras/${id}/bindings`,
        {
          bindings: bindings
            .filter((b) => b.enabled)
            .map((b) => ({
              pack_id: b.pack_id,
              parameters: b.parameters ?? {},
              report_interval_seconds: b.report_interval_seconds,
            })),
        }
      ),
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
  pipeline: {
    status: () => get<PipelineStatus>("/pipeline/status"),
    start: (adapter: string, nvidia_endpoint?: string, nvidia_api_key?: string) =>
      post<{ status: string; adapter: string }>("/pipeline/start", { adapter, nvidia_endpoint: nvidia_endpoint ?? "", nvidia_api_key: nvidia_api_key ?? "" }),
    stop: () => post<{ status: string }>("/pipeline/stop", {}),
    switchAdapter: (adapter: string, nvidia_endpoint?: string, nvidia_api_key?: string, local_model?: string, local_endpoint?: string) =>
      post<{ detection_adapter: string; pipeline: string }>("/cameras/config/adapter", { detection_adapter: adapter, nvidia_endpoint: nvidia_endpoint ?? "", nvidia_api_key: nvidia_api_key ?? "", local_model: local_model ?? "", local_endpoint: local_endpoint ?? "" }),
  },
  runtime: () => get<Record<string, unknown>>("/runtime"),
  localInference: {
    ollama: {
      status: (endpoint?: string) => get<{ running: boolean; endpoint: string; version: string | null }>(
        `/inference/ollama/status${endpoint ? `?endpoint=${encodeURIComponent(endpoint)}` : ""}`
      ),
      models: (endpoint?: string) => get<{ running: boolean; models: OllamaModel[] }>(
        `/inference/ollama/models${endpoint ? `?endpoint=${encodeURIComponent(endpoint)}` : ""}`
      ),
    },
    vllm: {
      status: (endpoint?: string) => get<{ running: boolean; endpoint: string; model_count: number }>(
        `/inference/vllm/status${endpoint ? `?endpoint=${encodeURIComponent(endpoint)}` : ""}`
      ),
      models: (endpoint?: string) => get<{ running: boolean; models: OllamaModel[] }>(
        `/inference/vllm/models${endpoint ? `?endpoint=${encodeURIComponent(endpoint)}` : ""}`
      ),
    },
    catalog: () => get<{ models: CatalogModel[] }>("/inference/catalog"),
  },
  snapshotUrl: (cameraId: string) =>
    `${BASE}/stream/${cameraId}/snapshot.jpg?t=${Date.now()}`,
};
