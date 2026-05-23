from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _read_schema() -> str:
    return _SCHEMA_PATH.read_text(encoding="utf-8")


class ConfigStore:
    """Async SQLite-backed store for camera config, bindings, calibrations, and audit."""

    def __init__(self, db_path: str = "store/urbanvision.sqlite") -> None:
        self._db_path = db_path
        self._initialized = False

    async def init(self) -> None:
        """Apply schema (idempotent — uses CREATE TABLE IF NOT EXISTS)."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_read_schema())
            # Migrate existing databases: add new columns if they don't exist
            async with db.execute("PRAGMA table_info(cameras)") as cur:
                cols = {row[1] for row in await cur.fetchall()}
            if "synthetic" not in cols:
                await db.execute(
                    "ALTER TABLE cameras ADD COLUMN synthetic INTEGER DEFAULT 0"
                )
            await db.commit()
        self._initialized = True

    async def _ensure_init(self) -> None:
        """Lazy init — ensures schema exists even when lifespan is not triggered."""
        if not self._initialized:
            await self.init()

    # ── Cameras ───────────────────────────────────────────────────────────────

    async def list_cameras(self) -> list[dict]:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM cameras WHERE enabled = 1") as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_camera(self, camera_id: str) -> dict | None:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM cameras WHERE id = ?", (camera_id,)
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def upsert_camera(self, camera: dict) -> None:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO cameras
                    (id, name, profile, rtsp_url, sample_fps, detection_adapter,
                     synthetic, timezone, enabled, retention_days)
                VALUES
                    (:id, :name, :profile, :rtsp_url, :sample_fps, :detection_adapter,
                     :synthetic, :timezone, :enabled, :retention_days)
                ON CONFLICT(id) DO UPDATE SET
                    name               = excluded.name,
                    profile            = excluded.profile,
                    rtsp_url           = excluded.rtsp_url,
                    sample_fps         = excluded.sample_fps,
                    detection_adapter  = excluded.detection_adapter,
                    synthetic          = excluded.synthetic,
                    timezone           = excluded.timezone,
                    enabled            = excluded.enabled,
                    retention_days     = excluded.retention_days
                """,
                {
                    "id": camera.get("id", str(uuid.uuid4())),
                    "name": camera.get("name", camera.get("id", "unnamed")),
                    "profile": camera.get("profile"),
                    "rtsp_url": camera.get("rtsp_url"),
                    "sample_fps": camera.get("sample_fps", 1.0),
                    "detection_adapter": camera.get("detection_adapter", "mock"),
                    "synthetic": 1 if camera.get("synthetic", False) else 0,
                    "timezone": camera.get("timezone", "UTC"),
                    "enabled": 1 if camera.get("enabled", True) else 0,
                    "retention_days": camera.get("retention_days", 30),
                },
            )
            await db.commit()

    # ── Bindings ──────────────────────────────────────────────────────────────

    async def get_bindings(self, camera_id: str) -> list[dict]:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM bindings WHERE camera_id = ? AND enabled = 1",
                (camera_id,),
            ) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def replace_bindings(self, camera_id: str, bindings: list[dict]) -> None:
        """Atomically replace all bindings for a camera."""
        await self._ensure_init()
        now = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "DELETE FROM bindings WHERE camera_id = ?", (camera_id,)
            )
            for b in bindings:
                await db.execute(
                    """
                    INSERT INTO bindings
                        (id, camera_id, pack_id, parameters_json,
                         report_interval_seconds, enabled, version, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        camera_id,
                        b["pack_id"],
                        json.dumps(b.get("parameters", {})),
                        b["report_interval_seconds"],
                        b.get("version", "1.0.0"),
                        now,
                    ),
                )
            await db.commit()

    # ── Speed calibration ─────────────────────────────────────────────────────

    async def get_speed_calibration(self, camera_id: str) -> dict | None:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM speed_calibrations WHERE camera_id = ?", (camera_id,)
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def save_speed_calibration(self, camera_id: str, data: dict) -> None:
        await self._ensure_init()
        now = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO speed_calibrations
                    (id, camera_id, gate_a_json, gate_b_json,
                     real_world_distance_m, homography_json, captured_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(camera_id) DO UPDATE SET
                    gate_a_json            = excluded.gate_a_json,
                    gate_b_json            = excluded.gate_b_json,
                    real_world_distance_m  = excluded.real_world_distance_m,
                    homography_json        = excluded.homography_json,
                    captured_at            = excluded.captured_at
                """,
                (
                    str(uuid.uuid4()),
                    camera_id,
                    json.dumps(data.get("gate_a", [])),
                    json.dumps(data.get("gate_b", [])),
                    data.get("real_world_distance_m", 0.0),
                    json.dumps(data.get("homography")) if data.get("homography") else None,
                    now,
                ),
            )
            await db.commit()

    # ── Stop zones ────────────────────────────────────────────────────────────

    async def get_stop_zone(self, camera_id: str) -> dict | None:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM stop_zones WHERE camera_id = ?", (camera_id,)
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def save_stop_zone(self, camera_id: str, data: dict) -> None:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO stop_zones
                    (id, camera_id, polygon_json, approach_direction,
                     compliance_threshold_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(camera_id) DO UPDATE SET
                    polygon_json               = excluded.polygon_json,
                    approach_direction         = excluded.approach_direction,
                    compliance_threshold_json  = excluded.compliance_threshold_json
                """,
                (
                    str(uuid.uuid4()),
                    camera_id,
                    json.dumps(data.get("polygon", [])),
                    data.get("approach_direction", "N"),
                    json.dumps(data.get("compliance_thresholds", {})),
                ),
            )
            await db.commit()

    # ── Audit ─────────────────────────────────────────────────────────────────

    async def append_audit(
        self,
        action: str,
        target_kind: str,
        target_id: str,
        payload: dict,
    ) -> None:
        await self._ensure_init()
        now = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO audit (id, action, target_kind, target_id, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    action,
                    target_kind,
                    target_id,
                    json.dumps(payload),
                    now,
                ),
            )
            await db.commit()
