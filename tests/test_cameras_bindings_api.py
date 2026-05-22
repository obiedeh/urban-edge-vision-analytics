"""Integration tests for the cameras + bindings API."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


# ── /use-cases ────────────────────────────────────────────────────────────────


def test_list_use_cases() -> None:
    resp = client.get("/use-cases")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 3
    pack_ids = {d["pack_id"] for d in data}
    assert "moving_object" in pack_ids
    assert "speed_violation" in pack_ids
    assert "stop_sign" in pack_ids


def test_use_case_has_schema() -> None:
    resp = client.get("/use-cases")
    for pack in resp.json():
        assert "parameters_schema" in pack
        assert "version" in pack
        assert "requires" in pack


# ── /cameras/{id}/bindings — report_interval validation ──────────────────────


def test_put_bindings_invalid_report_interval_422() -> None:
    resp = client.put(
        "/cameras/cam-test/bindings",
        json={"bindings": [{"pack_id": "moving_object", "report_interval_seconds": 1}]},
    )
    assert resp.status_code == 422


# ── /cameras/{id}/bindings — compatibility rule ───────────────────────────────


def test_put_bindings_incompatible_speed_stop_422() -> None:
    resp = client.put(
        "/cameras/cam-test/bindings",
        json={
            "bindings": [
                {"pack_id": "speed_violation", "report_interval_seconds": 5},
                {"pack_id": "stop_sign", "report_interval_seconds": 5},
            ]
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error"] == "incompatible_pack_selection"
    assert "allowed_sets" in detail


def test_put_bindings_incompatible_all_three_422() -> None:
    resp = client.put(
        "/cameras/cam-test/bindings",
        json={
            "bindings": [
                {"pack_id": "moving_object", "report_interval_seconds": 5},
                {"pack_id": "speed_violation", "report_interval_seconds": 5},
                {"pack_id": "stop_sign", "report_interval_seconds": 5},
            ]
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "incompatible_pack_selection"


# ── /cameras/{id}/bindings — prerequisite checks ──────────────────────────────


def test_put_bindings_speed_pack_without_calibration_422() -> None:
    resp = client.put(
        "/cameras/cam-no-cal/bindings",
        json={"bindings": [{"pack_id": "speed_violation", "report_interval_seconds": 5}]},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error"] == "missing_prerequisite"
    assert detail["prerequisite"] == "speed_calibration"


def test_put_bindings_stop_pack_without_zone_422() -> None:
    resp = client.put(
        "/cameras/cam-no-zone/bindings",
        json={"bindings": [{"pack_id": "stop_sign", "report_interval_seconds": 5}]},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error"] == "missing_prerequisite"
    assert detail["prerequisite"] == "stop_zone"


# ── Full happy-path: save cal → save zone → put bindings ─────────────────────


def test_full_moving_object_binding_happy_path() -> None:
    cam = "cam-happy-1"
    resp = client.put(
        f"/cameras/{cam}/bindings",
        json={"bindings": [{"pack_id": "moving_object", "report_interval_seconds": 5}]},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "saved"


def test_speed_calibration_then_binding() -> None:
    cam = "cam-speed-1"
    # Save calibration
    cal_resp = client.post(
        f"/cameras/{cam}/speed-calibration",
        json={
            "gate_a": {"x": 0, "y": 0, "width": 100, "height": 10},
            "gate_b": {"x": 0, "y": 200, "width": 100, "height": 10},
            "real_world_distance_m": 20.0,
        },
    )
    assert cal_resp.status_code == 201

    # Now binding should succeed
    bind_resp = client.put(
        f"/cameras/{cam}/bindings",
        json={"bindings": [{"pack_id": "speed_violation", "report_interval_seconds": 5}]},
    )
    assert bind_resp.status_code == 200


def test_stop_zone_then_binding() -> None:
    cam = "cam-stop-1"
    # Save stop zone
    zone_resp = client.put(
        f"/cameras/{cam}/stop-zone",
        json={"polygon": [[0, 0], [100, 0], [100, 100], [0, 100]]},
    )
    assert zone_resp.status_code == 200

    # Now binding should succeed
    bind_resp = client.put(
        f"/cameras/{cam}/bindings",
        json={"bindings": [{"pack_id": "stop_sign", "report_interval_seconds": 4}]},
    )
    assert bind_resp.status_code == 200


def test_get_bindings(db_init_cam: str) -> None:
    resp = client.get(f"/cameras/{db_init_cam}/bindings")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.fixture
def db_init_cam() -> str:
    cam = "cam-get-bindings"
    client.put(
        f"/cameras/{cam}/bindings",
        json={"bindings": [{"pack_id": "moving_object", "report_interval_seconds": 5}]},
    )
    return cam


# ── /metrics/kpis ─────────────────────────────────────────────────────────────


def test_metrics_kpis_has_data_source() -> None:
    resp = client.get("/metrics/kpis")
    assert resp.status_code == 200
    data = resp.json()
    assert "data_source" in data
    assert data["data_source"] in ("mock", "live-rtsp", "validated-benchmark")


def test_metrics_kpis_mock_has_tooltip() -> None:
    resp = client.get("/metrics/kpis")
    data = resp.json()
    if data["data_source"] == "mock":
        assert "tooltip" in data


def test_metrics_flow_has_data_source() -> None:
    resp = client.get("/metrics/flow")
    assert resp.status_code == 200
    assert "data_source" in resp.json()


# ── /stream/{camera_id}/snapshot.jpg ─────────────────────────────────────────


def test_snapshot_returns_jpeg() -> None:
    resp = client.get("/stream/cam-1/snapshot.jpg")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content[:2] == b"\xff\xd8"


def test_snapshot_no_cache_header() -> None:
    resp = client.get("/stream/cam-x/snapshot.jpg")
    assert resp.headers.get("cache-control") == "no-store"


# ── /speed-calibration ────────────────────────────────────────────────────────


def test_get_speed_calibration_not_found() -> None:
    resp = client.get("/cameras/cam-none/speed-calibration")
    assert resp.status_code == 404


def test_save_and_get_speed_calibration() -> None:
    cam = "cam-cal-get"
    client.post(
        f"/cameras/{cam}/speed-calibration",
        json={
            "gate_a": {"x": 0, "y": 0, "width": 100, "height": 10},
            "gate_b": {"x": 0, "y": 200, "width": 100, "height": 10},
            "real_world_distance_m": 15.0,
        },
    )
    resp = client.get(f"/cameras/{cam}/speed-calibration")
    assert resp.status_code == 200
    assert resp.json()["real_world_distance_m"] == 15.0


# ── /stop-zone ────────────────────────────────────────────────────────────────


def test_get_stop_zone_not_found() -> None:
    resp = client.get("/cameras/cam-none/stop-zone")
    assert resp.status_code == 404


def test_save_and_get_stop_zone() -> None:
    cam = "cam-zone-get"
    poly = [[0, 0], [100, 0], [100, 100], [0, 100]]
    client.put(f"/cameras/{cam}/stop-zone", json={"polygon": poly})
    resp = client.get(f"/cameras/{cam}/stop-zone")
    assert resp.status_code == 200
    assert resp.json()["polygon"] == poly
