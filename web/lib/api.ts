const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {
  constructor(
    public status: number,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    public detail: any
  ) {
    super(`API ${status}`);
  }
}

/** Best-effort human message out of a FastAPI error body. */
export function apiErrorMessage(err: unknown, fallback = "Request failed"): string {
  if (err instanceof ApiError) {
    const d = err.detail?.detail ?? err.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      // pydantic validation error list
      return d
        .map((x) => {
          const loc = Array.isArray(x?.loc) ? x.loc.filter((p: unknown) => p !== "body").join(".") : "";
          const msg = String(x?.msg ?? "").replace(/^Value error, /, "");
          return loc ? `${loc}: ${msg}` : msg;
        })
        .join("; ");
    }
    if (d && typeof d === "object") {
      if (typeof d.message === "string") return d.message;
      return JSON.stringify(d);
    }
    return `${fallback} (HTTP ${err.status})`;
  }
  return err instanceof Error ? err.message : fallback;
}

async function parseError(res: Response): Promise<never> {
  const detail = await res.json().catch(() => ({}));
  throw new ApiError(res.status, detail);
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) await parseError(res);
  return res.json() as Promise<T>;
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) await parseError(res);
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const put = <T,>(path: string, body: unknown) => send<T>("PUT", path, body);
const post = <T,>(path: string, body: unknown) => send<T>("POST", path, body);
const del = (path: string) => send<void>("DELETE", path);

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

// ── Cameras ───────────────────────────────────────────────────────────────────

export type CameraState =
  | "starting"
  | "connecting"
  | "streaming"
  | "reconnecting"
  | "error"
  | "stopped";

export interface CameraProfile {
  model_type: string;
  label: string;
  default_port: number;
  main_path: string;
  sub_path: string;
  protocol: string;
  requires_auth: boolean;
  requires_host: boolean;
  notes: string;
  example_main_path: string;
  example_sub_path: string;
}

export interface CameraRuntime {
  camera_id: string;
  kind: string;
  state: CameraState;
  fps: number;
  frames_decoded: number;
  frames_published: number;
  frames_dropped: number;
  decode_errors: number;
  reconnects: number;
  codec: string | null;
  source_width: number | null;
  source_height: number | null;
  source_fps: number | null;
  uptime_s: number | null;
  last_frame_age_s: number | null;
  last_error: string | null;
  frame: { width: number; height: number; seq: number } | null;
}

export interface Camera {
  id: string;
  name: string;
  profile: string;
  host: string;
  port: number | null;
  username: string;
  has_password: boolean;
  stream_path: string;
  effective_stream_path: string;
  stream_quality: "main" | "sub";
  channel: number;
  rtsp_transport: "tcp" | "udp";
  enabled: boolean;
  show_on_live: boolean;
  masked_url: string;
  created_at: string | null;
  updated_at: string | null;
  runtime: CameraRuntime | null;
}

export interface CameraIn {
  name: string;
  profile: string;
  host: string;
  port?: number | null;
  username: string;
  password: string;
  stream_path: string;
  stream_quality: "main" | "sub";
  channel: number;
  rtsp_transport: "tcp" | "udp";
  enabled: boolean;
  show_on_live: boolean;
}

export type ProbeStage =
  | "reachability"
  | "auth"
  | "path"
  | "codec"
  | "timeout"
  | "decode"
  | "url"
  | "ok";

export interface CameraTestResult {
  ok: boolean;
  stage: ProbeStage;
  error: string | null;
  width?: number | null;
  height?: number | null;
  codec?: string | null;
  fps?: number | null;
  open_ms?: number | null;
  masked_url: string;
  thumbnail_data_url?: string | null;
  note?: string;
}

/** Binding row as returned by GET /cameras/{id}/bindings (only enabled rows). */
export interface Binding {
  pack_id: string;
  parameters: Record<string, unknown>;
  report_interval_seconds: number;
}

export interface UseCasePack {
  pack_id: string;
  version: string;
  requires: string[];
  parameters_schema: Record<string, unknown>;
}

export type Point = [number, number];

export interface StopZoneThresholds {
  dwell_threshold_ms?: number;
  stop_speed_threshold?: number;
  rolling_speed_threshold?: number;
  report_compliant?: boolean;
}

export interface StopZone {
  polygon: Point[];
  approach_direction: string;
  compliance_thresholds: StopZoneThresholds;
}

export interface SpeedCalibration {
  gate_a: Point[];
  gate_b: Point[];
  real_world_distance_m: number;
  posted_speed_kph: number;
}

// ── Live inference ────────────────────────────────────────────────────────────

export interface Detection {
  track_id: string | null;
  label: string;
  confidence: number;
  /** normalized [x, y, w, h] 0..1 */
  bbox: [number, number, number, number];
}

export interface PackEventRef {
  pack_id: string;
  event_id: string;
  event_type: string;
  severity: string;
}

export type InferenceStatus = "ok" | "no_frame" | "inference_unavailable";

export interface InferenceResult {
  result_id: string;
  camera_id: string;
  frame_id: string;
  timestamp_ms: number;
  model_id: string;
  prompt_preset: string;
  vlm_summary: string | null;
  vlm_reasoning: string | null;
  raw_response: string | null;
  parse_ok: boolean;
  vehicle_count: number;
  inference_latency_ms: number | null;
  event: TrafficEvent | null;
  metadata: {
    status: InferenceStatus;
    detections: Detection[];
    frame_seq?: number;
    frame_size?: [number, number];
    pack_events?: PackEventRef[];
    camera_state?: CameraState;
    model_error?: string | null;
    [key: string]: unknown;
  };
}

export interface WebRTCAnswer {
  session_id: string;
  sdp: string;
  type: RTCSdpType;
}

// ── Settings / runtime ────────────────────────────────────────────────────────

export type ModelBackend = "vllm" | "ollama" | "nim" | "mock";

export interface ModelSettings {
  backend: ModelBackend;
  endpoint: string;
  model: string;
  /** write-only; send "" to keep the stored key */
  api_key: string;
  has_api_key: boolean;
  think: boolean;
  max_tokens: number;
  timeout_s: number;
  label: string;
}

export interface InferenceSettings {
  interval_ms: number;
  width: number;
  height: number;
  prompt_preset: string;
  jpeg_quality: number;
  display_max_width: number;
}

export interface LiveSettings {
  camera_ids: string[];
}

export interface PromptPreset {
  id: string;
  label: string;
  focus: string;
  description: string;
}

export interface HostCapabilities {
  hostname: string;
  machine: string;
  is_jetson: boolean;
  jetson_model: string | null;
  gpu_name: string | null;
  gpu_vram_total_gb: number | null;
  gpu_vram_free_gb: number | null;
  ram_total_gb: number | null;
  ram_available_gb: number | null;
  unified_memory: boolean;
  has_docker: boolean;
  has_vllm_binary: boolean;
  has_ollama: boolean;
  recommended_profile: string;
}

export interface ModelStatus {
  backend: ModelBackend;
  model: string;
  endpoint: string;
  label: string;
  think: boolean;
  state: "idle" | "healthy" | "unavailable";
  healthy: boolean;
  consecutive_failures: number;
  total_calls: number;
  total_failures: number;
  last_ok_at: number | null;
  last_error: string | null;
  last_error_at: number | null;
  latency: { n: number; p50_ms: number | null; p95_ms: number | null; mean_ms: number | null };
}

export interface RuntimeCameraStatus extends CameraRuntime {
  name: string;
  profile: string | null;
  packs: {
    active_packs: string[];
    tracks: number;
    events_emitted: number;
    last_error: string | null;
  } | null;
  last_inference: {
    status: InferenceStatus;
    age_s: number;
    latency_ms: number | null;
    detections: number;
  } | null;
}

export interface RuntimeStatus {
  started_at: number | null;
  host: HostCapabilities;
  model: ModelStatus | null;
  inference: InferenceSettings;
  cameras: RuntimeCameraStatus[];
}

// ── Model control ─────────────────────────────────────────────────────────────

export interface CatalogModel {
  name: string;
  hf_id: string | null;
  label: string;
  family: string;
  vision?: boolean;
  params_b: number;
  vram_gb: number;
  ram_gb?: number;
  tier: "nano" | "mid" | "high" | "max";
  backend: "ollama" | "vllm";
  description: string;
  pull_cmd: string;
  tags?: string[];
  gated?: boolean;
  access_note?: string;
  launch_bin?: string;
  served_model_name?: string;
  installed: boolean;
  can_run: boolean;
  blocked_reasons: string[];
  recommended: boolean;
  launcher: "ollama" | "vllm" | "docker";
}

export interface OllamaModel {
  name: string;
  size_gb?: number;
  family?: string;
  parameter_size?: string;
  vision: boolean;
  label?: string | null;
  tier?: string | null;
  vram_gb?: number | null;
  description?: string | null;
}

export interface VllmStatus {
  running: boolean;
  endpoint: string;
  model_count: number;
  managed: boolean;
  managed_state: "starting" | "stopped" | "failed" | null;
  managed_model: string | null;
  managed_pid: number | null;
  managed_log_tail: string[];
}

export interface VllmManaged {
  managed: boolean;
  launcher?: string | null;
  applied?: ModelSettings | null;
  state: "starting" | "failed" | "stopped";
  pid: number | null;
  model: string | null;
  endpoint: string | null;
  uptime_seconds?: number | null;
  exit_code?: number | null;
  log_tail: string[];
}

export interface VllmStartRequest {
  model: string;
  endpoint: string;
  launcher: "auto" | "binary" | "docker";
  model_path?: string;
  gpu_memory_utilization?: number;
  max_model_len?: number;
  apply: boolean;
}

export interface ApplyModelRequest {
  backend: ModelBackend;
  model: string;
  endpoint?: string;
  api_key?: string;
  think?: boolean;
  max_tokens?: number;
  label?: string;
}

// ── Events / review ───────────────────────────────────────────────────────────

export type ReviewStatus = "none" | "pending" | "confirmed" | "dismissed";

export interface TrafficEvent {
  event_id: string;
  camera_id: string;
  event_type: string;
  severity: "info" | "warning" | "critical" | string;
  confidence: number;
  timestamp: string;
  vehicle_count?: number;
  track_ids?: string[];
  operator_review_recommended?: boolean;
  vlm_summary?: string | null;
  vlm_reasoning?: string | null;
  vlm_model?: string | null;
  metadata: Record<string, unknown>;
  // pack fields (present depending on pack)
  pack_id?: string;
  track_id?: string;
  /** packs emit an object; older/ingested events may carry a compass string */
  direction?: string | { compass?: string; heading_deg?: number | null; velocity_px_per_s?: number | null };
  decision?: "compliant" | "rolling_stop" | "no_stop";
  dwell_ms?: number;
  min_speed_in_zone?: number;
  measured_speed?: number;
  posted_speed?: number;
  exceedance?: number;
  unit?: string;
  vehicle_type?: string;
  vehicle_color?: string;
  vehicle_descriptor?: string;
  person_descriptor?: string;
  attributes?: Record<string, unknown>;
  // review
  review_status?: ReviewStatus;
  review_note?: string | null;
  reviewed_at?: string | null;
  [key: string]: unknown;
}

export interface ReviewQueue {
  counts: { pending: number; confirmed: number; dismissed: number };
  events: TrafficEvent[];
}

export interface Incident {
  incident_id: string;
  camera_id: string;
  event_ids: string[];
  status: string;
  summary: string;
  created_at: string;
  [key: string]: unknown;
}

// ── Metrics / artifacts ───────────────────────────────────────────────────────

export type DataSource = "mock" | "live-rtsp" | "validated-benchmark";

export interface KpiTile {
  key: string;
  label: string;
  value: number | string | null;
  unit?: string;
  data_source: DataSource;
  tooltip?: string;
}

export interface KpisResponse {
  tiles: KpiTile[];
  adapter: string;
  data_source?: DataSource;
}

export interface FlowResponse {
  window_start: string;
  window_end: string;
  vehicle_count: number;
  person_count: number;
  congestion_windows: number;
  class_counts: Record<string, number>;
  data_source: DataSource;
  tooltip?: string;
}

export interface ArtifactEntry {
  path: string;
  kind: string;
  size_bytes: number;
  last_modified: string;
}

// ── API surface ───────────────────────────────────────────────────────────────

export const api = {
  cameras: {
    profiles: () => get<CameraProfile[]>("/cameras/profiles"),
    list: () => get<Camera[]>("/cameras"),
    get: (id: string) => get<Camera>(`/cameras/${encodeURIComponent(id)}`),
    create: (body: CameraIn) => post<Camera>("/cameras", body),
    update: (id: string, body: CameraIn) => put<Camera>(`/cameras/${encodeURIComponent(id)}`, body),
    remove: (id: string) => del(`/cameras/${encodeURIComponent(id)}`),
    setEnabled: (id: string, enabled: boolean) =>
      post<Camera>(`/cameras/${encodeURIComponent(id)}/enabled`, { enabled }),
    testUnsaved: (body: CameraIn) => post<CameraTestResult>("/cameras/test", body),
    testSaved: (id: string) => post<CameraTestResult>(`/cameras/${encodeURIComponent(id)}/test`, {}),

    bindings: (id: string) => get<Binding[]>(`/cameras/${encodeURIComponent(id)}/bindings`),
    putBindings: (id: string, bindings: Binding[]) =>
      put<{ camera_id: string; bindings: number; status: string }>(
        `/cameras/${encodeURIComponent(id)}/bindings`,
        {
          bindings: bindings.map((b) => ({
            pack_id: b.pack_id,
            parameters: b.parameters ?? {},
            report_interval_seconds: b.report_interval_seconds,
          })),
        }
      ),
    stopZone: (id: string) => get<StopZone>(`/cameras/${encodeURIComponent(id)}/stop-zone`),
    putStopZone: (id: string, zone: StopZone) =>
      put<{ camera_id: string; status: string }>(`/cameras/${encodeURIComponent(id)}/stop-zone`, zone),
    speedCalibration: (id: string) =>
      get<SpeedCalibration>(`/cameras/${encodeURIComponent(id)}/speed-calibration`),
    putSpeedCalibration: (id: string, cal: SpeedCalibration) =>
      post<{ camera_id: string; status: string }>(
        `/cameras/${encodeURIComponent(id)}/speed-calibration`,
        cal
      ),
  },

  useCases: {
    list: () => get<UseCasePack[]>("/use-cases"),
  },

  stream: {
    mjpegUrl: (cameraId: string, maxFps?: number) =>
      `${BASE}/stream/${encodeURIComponent(cameraId)}/live.mjpeg${maxFps ? `?max_fps=${maxFps}` : ""}`,
    snapshotUrl: (cameraId: string) =>
      `${BASE}/stream/${encodeURIComponent(cameraId)}/snapshot.jpg?t=${Date.now()}`,
    status: (cameraId: string) => get<CameraRuntime>(`/stream/${encodeURIComponent(cameraId)}/status`),
  },

  live: {
    resultsUrl: (cameraId?: string) =>
      `${BASE}/live/results${cameraId ? `?camera_id=${encodeURIComponent(cameraId)}` : ""}`,
    latest: () => get<Record<string, InferenceResult>>("/live/latest"),
  },

  webrtc: {
    offer: (payload: { sdp: string; type: RTCSdpType; camera_id: string; session_id?: string }) =>
      post<WebRTCAnswer>("/webrtc/offer", payload),
    close: (sessionId: string) => del(`/webrtc/${encodeURIComponent(sessionId)}`),
  },

  settings: {
    model: () => get<ModelSettings>("/settings/model"),
    putModel: (body: ModelSettings) => put<ModelSettings>("/settings/model", body),
    modelDefault: () =>
      get<{ host: HostCapabilities; default: Partial<ModelSettings> }>("/settings/model/default"),
    inference: () => get<InferenceSettings>("/settings/inference"),
    putInference: (body: InferenceSettings) => put<InferenceSettings>("/settings/inference", body),
    promptPresets: () => get<PromptPreset[]>("/settings/prompt-presets"),
    live: () => get<LiveSettings>("/settings/live"),
    putLive: (body: LiveSettings) => put<LiveSettings>("/settings/live", body),
  },

  runtime: {
    status: () => get<RuntimeStatus>("/runtime/status"),
    host: () => get<HostCapabilities>("/host/capabilities"),
  },

  inference: {
    catalog: () => get<{ host: HostCapabilities; models: CatalogModel[] }>("/inference/catalog"),
    apply: (body: ApplyModelRequest) =>
      post<{ applied: ModelSettings | null; runtime: ModelStatus | null }>("/inference/apply", body),
    ollama: {
      status: (endpoint?: string) =>
        get<{ running: boolean; endpoint: string; version: string | null }>(
          `/inference/ollama/status${qs({ endpoint })}`
        ),
      models: (endpoint?: string) =>
        get<{ running: boolean; models: OllamaModel[] }>(`/inference/ollama/models${qs({ endpoint })}`),
    },
    vllm: {
      status: (endpoint?: string) => get<VllmStatus>(`/inference/vllm/status${qs({ endpoint })}`),
      models: (endpoint?: string) =>
        get<{ running: boolean; models: { name: string; vision: boolean }[] }>(
          `/inference/vllm/models${qs({ endpoint })}`
        ),
      start: (body: VllmStartRequest) => post<VllmManaged>("/inference/vllm/start", body),
      stop: () => post<VllmManaged>("/inference/vllm/stop", {}),
    },
  },

  events: {
    list: (params?: {
      camera_id?: string;
      limit?: number;
      before?: string;
      review_only?: boolean;
      review_status?: ReviewStatus;
      event_type?: string;
    }) => get<TrafficEvent[]>(`/events${qs({ ...(params ?? {}) })}`),
    get: (id: string) => get<TrafficEvent>(`/events/${encodeURIComponent(id)}`),
    reviewQueue: (status: "pending" | "confirmed" | "dismissed", limit = 100) =>
      get<ReviewQueue>(`/events/review-queue${qs({ status, limit })}`),
    review: (id: string, status: "pending" | "confirmed" | "dismissed", note = "") =>
      post<TrafficEvent>(`/events/${encodeURIComponent(id)}/review`, { status, note }),
  },

  incidents: {
    list: (status?: string) => get<Incident[]>(`/incidents${qs({ status })}`),
    get: (id: string) => get<Incident>(`/incidents/${encodeURIComponent(id)}`),
    transition: (id: string, action: string, note?: string) =>
      post<Incident>(`/incidents/${encodeURIComponent(id)}/transition`, { action, note: note ?? "" }),
  },

  metrics: {
    kpis: () => get<KpisResponse>("/metrics/kpis"),
    flow: () => get<FlowResponse>("/metrics/flow"),
    benchmarks: () => get<Record<string, Record<string, unknown> | null>>("/metrics/benchmarks"),
    inference: () => get<Record<string, unknown>>("/metrics/inference"),
  },

  artifacts: {
    list: () => get<ArtifactEntry[]>("/artifacts"),
    get: (path: string) => get<unknown>(`/artifacts/${encodeURIComponent(path)}`),
  },
};
