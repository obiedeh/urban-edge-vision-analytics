import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_runtime():
    resp = client.get("/runtime")
    assert resp.status_code == 200
    assert "uptime_seconds" in resp.json()


def test_ingest_event():
    resp = client.post("/events", json={
        "camera_id": "cam-001",
        "event_type": "vehicle_detected",
        "severity": "info",
        "vehicle_count": 3,
        "inference_latency_ms": 12.5,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["camera_id"] == "cam-001"
    assert "event_id" in data


def test_list_events_empty():
    resp = client.get("/events?camera_id=cam-nonexistent")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_event_not_found():
    resp = client.get("/events/nonexistent-id")
    assert resp.status_code == 404


def test_open_incident():
    event_resp = client.post("/events", json={
        "camera_id": "cam-002",
        "event_type": "red_light_violation",
        "severity": "critical",
        "vehicle_count": 1,
        "operator_review_recommended": True,
    })
    event_id = event_resp.json()["event_id"]
    resp = client.post("/incidents", json={
        "camera_id": "cam-002",
        "event_ids": [event_id],
        "severity": "critical",
        "summary": "Red light violation at intersection A",
    })
    assert resp.status_code == 201
    assert resp.json()["status"] == "open"


def test_update_incident():
    event_resp = client.post("/events", json={
        "camera_id": "cam-003",
        "event_type": "congestion_onset",
        "severity": "warning",
    })
    event_id = event_resp.json()["event_id"]
    incident_resp = client.post("/incidents", json={
        "camera_id": "cam-003",
        "event_ids": [event_id],
        "severity": "warning",
    })
    incident_id = incident_resp.json()["incident_id"]
    update_resp = client.patch(f"/incidents/{incident_id}", json={
        "status": "under_review",
        "notes": "Operator reviewing camera footage",
    })
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "under_review"


def test_update_incident_not_found():
    resp = client.patch("/incidents/nonexistent", json={"status": "resolved"})
    assert resp.status_code == 404


def test_inference_metrics():
    resp = client.get("/metrics/inference")
    assert resp.status_code == 200
    assert "sample_count" in resp.json()
