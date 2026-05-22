"""Tests for the SQLite config store — ≥ 80% coverage target.

Uses asyncio.run() directly so no pytest-asyncio plugin is required.
"""
from __future__ import annotations

import asyncio
import json

import pytest


@pytest.fixture
def store(tmp_path):
    from store.config_store import ConfigStore

    return ConfigStore(str(tmp_path / "test.sqlite"))


def run(coro):
    return asyncio.run(coro)


def test_init_creates_schema(store) -> None:
    run(store.init())
    # Second call is idempotent — CREATE TABLE IF NOT EXISTS
    run(store.init())


def test_upsert_and_list_cameras(store) -> None:
    run(store.upsert_camera({"id": "cam-1", "name": "Test Camera"}))
    cameras = run(store.list_cameras())
    assert len(cameras) == 1
    assert cameras[0]["id"] == "cam-1"


def test_upsert_camera_idempotent(store) -> None:
    run(store.upsert_camera({"id": "cam-1", "name": "First"}))
    run(store.upsert_camera({"id": "cam-1", "name": "Updated"}))
    cameras = run(store.list_cameras())
    assert len(cameras) == 1
    assert cameras[0]["name"] == "Updated"


def test_get_camera_not_found(store) -> None:
    run(store.init())
    result = run(store.get_camera("missing"))
    assert result is None


def test_replace_and_get_bindings(store) -> None:
    run(store.upsert_camera({"id": "cam-1", "name": "C1"}))
    bindings = [
        {"pack_id": "moving_object", "parameters": {}, "report_interval_seconds": 5},
    ]
    run(store.replace_bindings("cam-1", bindings))
    rows = run(store.get_bindings("cam-1"))
    assert len(rows) == 1
    assert rows[0]["pack_id"] == "moving_object"
    assert rows[0]["report_interval_seconds"] == 5


def test_replace_bindings_is_atomic(store) -> None:
    run(store.upsert_camera({"id": "cam-1", "name": "C1"}))
    run(store.replace_bindings(
        "cam-1",
        [{"pack_id": "moving_object", "parameters": {}, "report_interval_seconds": 5}],
    ))
    # Replace with a different set
    run(store.replace_bindings(
        "cam-1",
        [{"pack_id": "stop_sign", "parameters": {}, "report_interval_seconds": 3}],
    ))
    rows = run(store.get_bindings("cam-1"))
    assert len(rows) == 1
    assert rows[0]["pack_id"] == "stop_sign"


def test_speed_calibration_save_and_get(store) -> None:
    run(store.upsert_camera({"id": "cam-1", "name": "C1"}))
    data = {
        "gate_a": {"x": 0, "y": 0},
        "gate_b": {"x": 200, "y": 0},
        "real_world_distance_m": 20.0,
    }
    run(store.save_speed_calibration("cam-1", data))
    cal = run(store.get_speed_calibration("cam-1"))
    assert cal is not None
    assert json.loads(cal["gate_a_json"]) == data["gate_a"]
    assert cal["real_world_distance_m"] == 20.0


def test_speed_calibration_not_found(store) -> None:
    run(store.init())
    result = run(store.get_speed_calibration("missing"))
    assert result is None


def test_speed_calibration_upsert(store) -> None:
    run(store.upsert_camera({"id": "cam-1", "name": "C1"}))
    base = {"gate_a": {}, "gate_b": {}, "real_world_distance_m": 10}
    run(store.save_speed_calibration("cam-1", base))
    run(store.save_speed_calibration("cam-1", {**base, "real_world_distance_m": 25}))
    cal = run(store.get_speed_calibration("cam-1"))
    assert cal["real_world_distance_m"] == 25.0


def test_stop_zone_save_and_get(store) -> None:
    run(store.upsert_camera({"id": "cam-1", "name": "C1"}))
    data = {
        "polygon": [[0, 0], [100, 0], [100, 100], [0, 100]],
        "approach_direction": "N",
        "compliance_thresholds": {"dwell_ms": 1000},
    }
    run(store.save_stop_zone("cam-1", data))
    zone = run(store.get_stop_zone("cam-1"))
    assert zone is not None
    assert json.loads(zone["polygon_json"]) == data["polygon"]
    assert zone["approach_direction"] == "N"


def test_stop_zone_not_found(store) -> None:
    run(store.init())
    result = run(store.get_stop_zone("missing"))
    assert result is None


def test_audit_append(store) -> None:
    run(store.init())
    run(store.append_audit(
        "replace_bindings", "camera", "cam-1", {"pack_ids": ["moving_object"]}
    ))
    # No error — audit is append-only with no retrieval at MVP
