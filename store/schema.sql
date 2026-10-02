CREATE TABLE IF NOT EXISTS cameras (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    profile TEXT,
    rtsp_url TEXT,
    sample_fps REAL DEFAULT 1.0,
    detection_adapter TEXT DEFAULT 'mock',
    synthetic INTEGER DEFAULT 0,
    timezone TEXT DEFAULT 'UTC',
    enabled INTEGER DEFAULT 1,
    retention_days INTEGER DEFAULT 30
);
-- Columns added by ConfigStore.init() migrations:
--   host, port, username, password_enc, stream_path, stream_quality, channel,
--   rtsp_transport, show_on_live, created_at, updated_at

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS zones (
    id TEXT PRIMARY KEY,
    camera_id TEXT NOT NULL,
    name TEXT NOT NULL,
    polygon_json TEXT NOT NULL,
    kind TEXT NOT NULL,
    FOREIGN KEY (camera_id) REFERENCES cameras(id)
);

CREATE TABLE IF NOT EXISTS bindings (
    id TEXT PRIMARY KEY,
    camera_id TEXT NOT NULL,
    pack_id TEXT NOT NULL,
    parameters_json TEXT NOT NULL DEFAULT '{}',
    report_interval_seconds INTEGER NOT NULL DEFAULT 5,
    enabled INTEGER DEFAULT 1,
    version TEXT DEFAULT '1.0.0',
    updated_at TEXT NOT NULL,
    UNIQUE(camera_id, pack_id),
    FOREIGN KEY (camera_id) REFERENCES cameras(id)
);

CREATE TABLE IF NOT EXISTS speed_calibrations (
    id TEXT PRIMARY KEY,
    camera_id TEXT NOT NULL UNIQUE,
    gate_a_json TEXT NOT NULL,
    gate_b_json TEXT NOT NULL,
    real_world_distance_m REAL NOT NULL,
    homography_json TEXT,
    captured_at TEXT NOT NULL,
    FOREIGN KEY (camera_id) REFERENCES cameras(id)
);
-- Column added by migration: posted_speed_kph

CREATE TABLE IF NOT EXISTS stop_zones (
    id TEXT PRIMARY KEY,
    camera_id TEXT NOT NULL UNIQUE,
    polygon_json TEXT NOT NULL,
    approach_direction TEXT NOT NULL DEFAULT 'N',
    compliance_threshold_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (camera_id) REFERENCES cameras(id)
);

CREATE TABLE IF NOT EXISTS audit (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    camera_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    pack_id TEXT,
    operator_review_recommended INTEGER NOT NULL DEFAULT 0,
    review_status TEXT NOT NULL DEFAULT 'none',
    review_note TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_camera_ts ON events(camera_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_review ON events(operator_review_recommended, review_status);

CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    camera_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
