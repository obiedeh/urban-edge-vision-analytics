"""Async SQLite config store: cameras, uploads, settings, bindings, zones, audit.

Schema changes are additive. ``init()`` applies ``schema.sql`` (``CREATE IF
NOT EXISTS``) and then adds any column introduced after the first release
with a default, so a database written by an older build opens unchanged.
Camera passwords are Fernet-encrypted before they reach a row; pasted RTSP
links are stored without their credentials. Uploaded video files live in
``upload_dir`` next to the database, never inside the repository.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from store.models import (
    CameraIn,
    CameraRecord,
    InferenceSettings,
    LiveSettings,
    ModelSettings,
    UploadRecord,
)
from store.secrets import SecretBox
from vision.camera_profiles import CameraConfigError, get_profile, source_kind_for
from vision.redaction import REDACTOR, mask_url
from vision.rtsp_url import with_credentials

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_CAMERA_COLUMNS: dict[str, str] = {
    "host": "TEXT DEFAULT ''",
    "port": "INTEGER",
    "username": "TEXT DEFAULT ''",
    "password_enc": "TEXT DEFAULT ''",
    "stream_path": "TEXT DEFAULT ''",
    "stream_quality": "TEXT DEFAULT 'main'",
    "channel": "INTEGER DEFAULT 1",
    "rtsp_transport": "TEXT DEFAULT 'tcp'",
    "show_on_live": "INTEGER DEFAULT 1",
    "created_at": "TEXT",
    "updated_at": "TEXT",
    # video feed connectors (rtsp_url, usb, uploaded_video)
    "source_url": "TEXT DEFAULT ''",
    "device": "TEXT DEFAULT ''",
    "capture_width": "INTEGER",
    "capture_height": "INTEGER",
    "capture_fps": "REAL",
    "capture_format": "TEXT DEFAULT ''",
    "upload_id": "TEXT DEFAULT ''",
    "playback": "TEXT DEFAULT 'loop'",
}


def _read_schema() -> str:
    return _SCHEMA_PATH.read_text(encoding="utf-8")


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "camera"


class ConfigStore:
    """Async SQLite-backed store for cameras, settings, bindings, calibrations, audit."""

    def __init__(
        self,
        db_path: str = "store/urbanvision.sqlite",
        secrets: SecretBox | None = None,
        upload_dir: str | Path | None = None,
    ) -> None:
        self._db_path = db_path
        self._initialized = False
        self._secrets = secrets
        self._upload_dir = Path(upload_dir) if upload_dir else Path(db_path).parent / "uploads"

    @property
    def path(self) -> str:
        return self._db_path

    @property
    def upload_dir(self) -> Path:
        """Directory holding uploaded video files (next to the database by default)."""
        return self._upload_dir

    @property
    def secrets(self) -> SecretBox:
        if self._secrets is None:
            self._secrets = SecretBox()
        return self._secrets

    async def init(self) -> None:
        """Apply schema (idempotent) and add columns introduced after the first release."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_read_schema())
            await _add_missing_columns(db, "cameras", _CAMERA_COLUMNS)
            await _add_missing_columns(
                db, "speed_calibrations", {"posted_speed_kph": "REAL DEFAULT 50"}
            )
            await db.commit()
        self._initialized = True

    async def _ensure_init(self) -> None:
        if not self._initialized:
            await self.init()

    # ── Cameras ───────────────────────────────────────────────────────────────

    async def list_cameras(self, *, enabled_only: bool = False) -> list[CameraRecord]:
        await self._ensure_init()
        query = "SELECT * FROM cameras"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY created_at, name"
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query) as cur:
                rows = [dict(row) for row in await cur.fetchall()]
        uploads = {u.id: u for u in await self.list_uploads()} if any(
            r.get("upload_id") for r in rows
        ) else {}
        return [self._record(row, uploads.get(row.get("upload_id") or "")) for row in rows]

    async def get_camera(self, camera_id: str) -> CameraRecord | None:
        row = await self._row(camera_id)
        if not row:
            return None
        upload = await self.get_upload(row["upload_id"]) if row.get("upload_id") else None
        return self._record(row, upload)

    async def get_camera_secret(self, camera_id: str) -> str:
        """Decrypted password for the runtime only. Never returned by the API."""
        row = await self._row(camera_id)
        if not row:
            return ""
        return self.secrets.decrypt(row.get("password_enc") or "")

    async def feed_url(self, camera_id: str) -> str:
        """Full credentialed URL for the runtime. Registers the password with the redactor."""
        row = await self._row(camera_id)
        if not row:
            raise KeyError(camera_id)
        password = self.secrets.decrypt(row.get("password_enc") or "")
        REDACTOR.register(password)
        return _build_url(row, password)

    async def create_camera(self, data: CameraIn, camera_id: str | None = None) -> CameraRecord:
        await self._ensure_init()
        now = datetime.now(UTC).isoformat()
        new_id = (camera_id or "").strip() or await self._unique_id(_slug(data.name))
        enc = self.secrets.encrypt(data.password) if data.password else ""
        REDACTOR.register(data.password)
        _validate_url(data, data.password)
        await self._check_upload(data)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO cameras
                    (id, name, profile, rtsp_url, host, port, username, password_enc,
                     stream_path, stream_quality, channel, rtsp_transport, enabled,
                     show_on_live, synthetic, detection_adapter, created_at, updated_at,
                     source_url, device, capture_width, capture_height, capture_fps,
                     upload_id, playback, capture_format)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id, data.name, data.profile, None, data.host, data.port, data.username,
                    enc, data.stream_path, data.stream_quality, data.channel,
                    data.rtsp_transport, 1 if data.enabled else 0, 1 if data.show_on_live else 0,
                    1 if data.profile == "synthetic" else 0, now, now,
                    data.source_url, data.device, data.capture_width, data.capture_height,
                    data.capture_fps, data.upload_id, data.playback, data.capture_format,
                ),
            )
            await db.commit()
        record = await self.get_camera(new_id)
        assert record is not None
        return record

    async def update_camera(self, camera_id: str, data: CameraIn) -> CameraRecord | None:
        await self._ensure_init()
        row = await self._row(camera_id)
        if not row:
            return None
        now = datetime.now(UTC).isoformat()
        if data.password:
            enc = self.secrets.encrypt(data.password)
            password = data.password
            REDACTOR.register(password)
        else:
            enc = row.get("password_enc") or ""
            password = self.secrets.decrypt(enc)
        _validate_url(data, password)
        await self._check_upload(data)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                UPDATE cameras SET
                    name = ?, profile = ?, host = ?, port = ?, username = ?, password_enc = ?,
                    stream_path = ?, stream_quality = ?, channel = ?, rtsp_transport = ?,
                    enabled = ?, show_on_live = ?, synthetic = ?, updated_at = ?,
                    source_url = ?, device = ?, capture_width = ?, capture_height = ?,
                    capture_fps = ?, upload_id = ?, playback = ?, capture_format = ?
                WHERE id = ?
                """,
                (
                    data.name, data.profile, data.host, data.port, data.username, enc,
                    data.stream_path, data.stream_quality, data.channel, data.rtsp_transport,
                    1 if data.enabled else 0, 1 if data.show_on_live else 0,
                    1 if data.profile == "synthetic" else 0, now,
                    data.source_url, data.device, data.capture_width, data.capture_height,
                    data.capture_fps, data.upload_id, data.playback, data.capture_format,
                    camera_id,
                ),
            )
            await db.commit()
        return await self.get_camera(camera_id)

    async def set_camera_enabled(self, camera_id: str, enabled: bool) -> CameraRecord | None:
        await self._ensure_init()
        now = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                "UPDATE cameras SET enabled = ?, updated_at = ? WHERE id = ?",
                (1 if enabled else 0, now, camera_id),
            )
            await db.commit()
            if cur.rowcount == 0:
                return None
        return await self.get_camera(camera_id)

    async def delete_camera(self, camera_id: str) -> bool:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))
            for table in ("bindings", "stop_zones", "speed_calibrations", "zones"):
                await db.execute(f"DELETE FROM {table} WHERE camera_id = ?", (camera_id,))
            await db.commit()
            return cur.rowcount > 0

    async def upsert_camera(self, camera: dict) -> None:
        """Legacy minimal upsert (id, name, profile). Kept for the env-import path."""
        await self._ensure_init()
        now = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO cameras (id, name, profile, enabled, created_at, updated_at)
                VALUES (:id, :name, :profile, :enabled, :now, :now)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name, profile = excluded.profile,
                    enabled = excluded.enabled, updated_at = excluded.updated_at
                """,
                {
                    "id": camera.get("id", str(uuid.uuid4())),
                    "name": camera.get("name", camera.get("id", "unnamed")),
                    "profile": camera.get("profile"),
                    "enabled": 1 if camera.get("enabled", True) else 0,
                    "now": now,
                },
            )
            await db.commit()

    async def _row(self, camera_id: str) -> dict[str, Any] | None:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM cameras WHERE id = ?", (camera_id,)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def _unique_id(self, base: str) -> str:
        existing = {c.id for c in await self.list_cameras()}
        candidate = base
        n = 2
        while candidate in existing:
            candidate = f"{base}-{n}"
            n += 1
        return candidate

    def _record(self, row: dict[str, Any], upload: UploadRecord | None = None) -> CameraRecord:
        profile_key = row.get("profile") or "generic_rtsp"
        try:
            profile = get_profile(profile_key)
        except CameraConfigError:
            profile = get_profile("generic_rtsp")
        quality = row.get("stream_quality") or "main"
        channel = int(row.get("channel") or 1)
        effective = (row.get("stream_path") or "") or (
            profile.stream_path(quality, channel) if profile.requires_host else ""
        )
        masked = ""
        has_url = (profile.requires_host and row.get("host")) or (
            profile.connector == "rtsp_url" and row.get("source_url")
        )
        if has_url:
            masked = mask_url(_build_url(row, "x" if row.get("password_enc") else ""))
        return CameraRecord(
            id=row["id"],
            name=row.get("name") or row["id"],
            profile=profile.model_type,
            host=row.get("host") or "",
            port=row.get("port") or (profile.default_port if profile.requires_host else None),
            username=row.get("username") or "",
            has_password=bool(row.get("password_enc")),
            stream_path=row.get("stream_path") or "",
            effective_stream_path=effective,
            stream_quality=quality,
            channel=channel,
            rtsp_transport=row.get("rtsp_transport") or "tcp",
            enabled=bool(row.get("enabled", 1)),
            show_on_live=bool(row.get("show_on_live", 1)),
            masked_url=masked,
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            connector=profile.connector,
            source_url=row.get("source_url") or "",
            device=row.get("device") or "",
            capture_width=row.get("capture_width"),
            capture_height=row.get("capture_height"),
            capture_fps=row.get("capture_fps"),
            capture_format=row.get("capture_format") or "",
            upload_id=row.get("upload_id") or "",
            playback="once" if row.get("playback") == "once" else "loop",
            upload=upload,
            source_kind=source_kind_for(
                profile.model_type, upload.source_kind if upload else None
            ),
        )

    # ── Uploaded videos ───────────────────────────────────────────────────────

    def upload_path(self, record: UploadRecord) -> Path:
        """Where the bytes of ``record`` live on disk."""
        return self._upload_dir / (record.stored_name or record.id)

    async def list_uploads(self) -> list[UploadRecord]:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM uploads ORDER BY created_at DESC") as cur:
                rows = [dict(r) for r in await cur.fetchall()]
            users = await self._upload_users(db)
        return [UploadRecord(**row, camera_ids=users.get(row["id"], [])) for row in rows]

    async def get_upload(self, upload_id: str) -> UploadRecord | None:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM uploads WHERE id = ?", (upload_id,)) as cur:
                row = await cur.fetchone()
            if row is None:
                return None
            users = await self._upload_users(db, upload_id)
        return UploadRecord(**dict(row), camera_ids=users.get(upload_id, []))

    async def add_upload(self, record: UploadRecord) -> UploadRecord:
        """Insert (or replace, same id means same bytes) an upload row."""
        await self._ensure_init()
        data = record.model_dump(exclude={"camera_ids"})
        data["created_at"] = data.get("created_at") or datetime.now(UTC).isoformat()
        columns = ", ".join(data)
        placeholders = ", ".join(f":{k}" for k in data)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                f"INSERT OR REPLACE INTO uploads ({columns}) VALUES ({placeholders})", data
            )
            await db.commit()
        saved = await self.get_upload(record.id)
        assert saved is not None
        return saved

    async def delete_upload(self, upload_id: str) -> UploadRecord | None:
        """Remove the row and the file. Returns the record, or None if it did not exist."""
        record = await self.get_upload(upload_id)
        if record is None:
            return None
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM uploads WHERE id = ?", (upload_id,))
            await db.commit()
        try:
            self.upload_path(record).unlink(missing_ok=True)
        except OSError:
            pass
        return record

    async def _upload_users(
        self, db: aiosqlite.Connection, upload_id: str | None = None
    ) -> dict[str, list[str]]:
        query = "SELECT id, upload_id FROM cameras WHERE upload_id IS NOT NULL AND upload_id != ''"
        params: tuple[Any, ...] = ()
        if upload_id is not None:
            query += " AND upload_id = ?"
            params = (upload_id,)
        users: dict[str, list[str]] = {}
        async with db.execute(query, params) as cur:
            for row in await cur.fetchall():
                users.setdefault(str(row[1]), []).append(str(row[0]))
        return users

    async def _check_upload(self, data: CameraIn) -> None:
        if get_profile(data.profile).connector != "upload":
            return
        if await self.get_upload(data.upload_id) is None:
            raise ValueError(f"Uploaded video '{data.upload_id}' not found. Upload it first.")

    # ── Settings ──────────────────────────────────────────────────────────────

    async def get_setting(self, key: str) -> dict[str, Any] | None:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute("SELECT value_json FROM settings WHERE key = ?", (key,)) as cur:
                row = await cur.fetchone()
        return json.loads(row[0]) if row else None

    async def put_setting(self, key: str, value: dict[str, Any]) -> None:
        await self._ensure_init()
        now = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO settings (key, value_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json,
                                              updated_at = excluded.updated_at
                """,
                (key, json.dumps(value), now),
            )
            await db.commit()

    async def get_model_settings(self) -> ModelSettings:
        raw = await self.get_setting("model") or {}
        settings = ModelSettings.model_validate(
            {k: v for k, v in raw.items() if k != "api_key_enc"}
        )
        settings.has_api_key = bool(raw.get("api_key_enc"))
        settings.api_key = ""
        return settings

    async def get_model_api_key(self) -> str:
        raw = await self.get_setting("model") or {}
        key = self.secrets.decrypt(raw.get("api_key_enc") or "")
        REDACTOR.register(key)
        return key

    async def put_model_settings(self, settings: ModelSettings) -> ModelSettings:
        raw = await self.get_setting("model") or {}
        data = settings.model_dump()
        api_key = data.pop("api_key", "")
        data.pop("has_api_key", None)
        if api_key:
            REDACTOR.register(api_key)
            data["api_key_enc"] = self.secrets.encrypt(api_key)
        else:
            data["api_key_enc"] = raw.get("api_key_enc", "")
        await self.put_setting("model", data)
        return await self.get_model_settings()

    async def get_inference_settings(self) -> InferenceSettings:
        return InferenceSettings.model_validate(await self.get_setting("inference") or {})

    async def put_inference_settings(self, settings: InferenceSettings) -> InferenceSettings:
        await self.put_setting("inference", settings.model_dump())
        return settings

    async def get_live_settings(self) -> LiveSettings:
        return LiveSettings.model_validate(await self.get_setting("live") or {})

    async def put_live_settings(self, settings: LiveSettings) -> LiveSettings:
        await self.put_setting("live", settings.model_dump())
        return settings

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
            await db.execute("DELETE FROM bindings WHERE camera_id = ?", (camera_id,))
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
                     real_world_distance_m, homography_json, posted_speed_kph, captured_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(camera_id) DO UPDATE SET
                    gate_a_json            = excluded.gate_a_json,
                    gate_b_json            = excluded.gate_b_json,
                    real_world_distance_m  = excluded.real_world_distance_m,
                    homography_json        = excluded.homography_json,
                    posted_speed_kph       = excluded.posted_speed_kph,
                    captured_at            = excluded.captured_at
                """,
                (
                    str(uuid.uuid4()),
                    camera_id,
                    json.dumps(data.get("gate_a", [])),
                    json.dumps(data.get("gate_b", [])),
                    data.get("real_world_distance_m", 0.0),
                    json.dumps(data.get("homography")) if data.get("homography") else None,
                    float(data.get("posted_speed_kph") or 50.0),
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
        safe_payload = {
            k: v for k, v in payload.items()
            if k not in {"password", "api_key", "password_enc", "api_key_enc"}
        }
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
                    json.dumps(safe_payload),
                    now,
                ),
            )
            await db.commit()


async def _add_missing_columns(
    db: aiosqlite.Connection, table: str, columns: dict[str, str]
) -> None:
    async with db.execute(f"PRAGMA table_info({table})") as cur:
        existing = {row[1] for row in await cur.fetchall()}
    for name, decl in columns.items():
        if name not in existing:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _build_url(row: dict[str, Any], password: str) -> str:
    """Credentialed feed URL for a row; pasted links get their credentials put back."""
    profile = get_profile(row.get("profile") or "generic_rtsp")
    if profile.connector == "rtsp_url":
        return with_credentials(
            row.get("source_url") or "", row.get("username") or None, password or None
        )
    return profile.build_url(
        host=row.get("host") or "",
        username=row.get("username") or None,
        password=password or None,
        port=int(row["port"]) if row.get("port") else None,
        channel=int(row.get("channel") or 1),
        quality=row.get("stream_quality") or "main",
        path=row.get("stream_path") or None,
    )


def _validate_url(data: CameraIn, password: str) -> None:
    profile = get_profile(data.profile)
    if not profile.requires_host:
        return
    try:
        profile.build_url(
            host=data.host,
            username=data.username or None,
            password=password or None,
            port=data.port,
            channel=data.channel,
            quality=data.stream_quality,
            path=data.stream_path or None,
        )
    except CameraConfigError as exc:
        raise ValueError(str(exc)) from exc
