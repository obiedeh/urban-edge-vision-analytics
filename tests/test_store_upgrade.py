"""A config store written by the previous main opens unchanged after the connector migration.

``tests/fixtures/config_store_main.sql`` is a dump of a database created by the
code on ``main`` before the video-feed connectors existed, with seven cameras
(one per original connector family), bindings, a stop zone, a speed
calibration and model settings. ``config_store_main.expected.json`` holds what
that code returned for them. The test loads the dump, runs the current
migrations and checks every camera, secret, URL and setting comes back
identical, with the new fields at their defaults.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from store.config_store import ConfigStore
from store.event_store import SqliteEventStore
from store.secrets import SecretBox
from vision.camera_profiles import CameraConfigError

FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED = json.loads((FIXTURES / "config_store_main.expected.json").read_text())


@pytest.fixture
def legacy_db(tmp_path) -> str:
    db = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript((FIXTURES / "config_store_main.sql").read_text())
    conn.commit()
    conn.close()
    return str(db)


def test_fixture_is_from_the_old_schema(legacy_db) -> None:
    conn = sqlite3.connect(legacy_db)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(cameras)")}
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "source_url" not in cols and "upload_id" not in cols
    assert "uploads" not in tables
    assert len(EXPECTED["cameras"]) == 7


async def test_cameras_survive_the_upgrade_unchanged(legacy_db) -> None:
    store = ConfigStore(legacy_db, secrets=SecretBox(key=EXPECTED["secret_key"]))
    await store.init()
    await store.init()  # migrations are idempotent
    cameras = {c.id: c for c in await store.list_cameras()}
    assert list(cameras) == [c["id"] for c in EXPECTED["cameras"]]
    for expected in EXPECTED["cameras"]:
        got = cameras[expected["id"]].model_dump()
        for key, value in expected.items():
            assert got[key] == value, (expected["id"], key)
        # New fields exist with their defaults.
        assert got["source_url"] == "" and got["device"] == "" and got["upload_id"] == ""
        assert got["capture_format"] == "" and got["capture_fps"] is None
        assert got["playback"] == "loop" and got["upload"] is None
        expected_connector = {"browser_webrtc": "browser", "synthetic": "synthetic"}.get(
            expected["profile"], "network"
        )
        assert got["connector"] == expected_connector
        assert got["source_kind"] == {"browser": "browser", "synthetic": "synthetic"}.get(
            expected_connector, "live_rtsp"
        )
        assert (await store.get_camera(expected["id"])).model_dump() == got

    for camera_id, secret in EXPECTED["camera_secrets"].items():
        assert await store.get_camera_secret(camera_id) == secret
    for camera_id, url in EXPECTED["feed_urls"].items():
        if url.startswith("ERROR:"):
            with pytest.raises(CameraConfigError):
                await store.feed_url(camera_id)
        else:
            assert await store.feed_url(camera_id) == url


async def test_bindings_zones_and_settings_survive(legacy_db) -> None:
    store = ConfigStore(legacy_db, secrets=SecretBox(key=EXPECTED["secret_key"]))
    for camera_id, rows in EXPECTED["bindings"].items():
        got = [
            {k: v for k, v in b.items() if k not in {"id", "updated_at"}}
            for b in await store.get_bindings(camera_id)
        ]
        assert got == rows
    zone_cam = next(iter(EXPECTED["stop_zone"]["camera_id"],))
    zone = await store.get_stop_zone(EXPECTED["stop_zone"]["camera_id"])
    assert zone is not None and zone_cam
    assert {k: v for k, v in zone.items() if k != "id"} == EXPECTED["stop_zone"]
    cal = await store.get_speed_calibration(EXPECTED["speed_calibration"]["camera_id"])
    assert cal is not None
    assert {k: v for k, v in cal.items() if k not in {"id", "captured_at"}} == (
        EXPECTED["speed_calibration"]
    )
    assert (await store.get_inference_settings()).model_dump() == EXPECTED["inference"]
    assert (await store.get_model_settings()).model_dump() == EXPECTED["model"]
    assert await store.get_model_api_key() == EXPECTED["model_api_key"]
    # New tables are present and empty; the event store opens on the same file.
    assert await store.list_uploads() == []
    events = SqliteEventStore(legacy_db)
    assert events.count_events() == 0
