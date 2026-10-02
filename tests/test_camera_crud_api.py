"""Camera CRUD, enable/disable, test-connection and credential handling over HTTP."""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

import api.main as main_mod
from api.main import app
from api.routes import cameras as cam_routes

client = TestClient(app)

TAPO = {
    "name": "Front Door",
    "profile": "tapo",
    "host": "192.0.2.20",
    "username": "viewer",
    "password": "s3cret-pass",
    "stream_quality": "sub",
}


@pytest.fixture(autouse=True)
def _clean_cameras():
    yield
    for cam in client.get("/cameras").json():
        client.delete(f"/cameras/{cam['id']}")


def test_profiles_endpoint_lists_vendor_profiles() -> None:
    profiles = {p["model_type"]: p for p in client.get("/cameras/profiles").json()}
    assert "tapo" in profiles and profiles["tapo"]["example_sub_path"] == "/stream2"
    assert "browser_webrtc" in profiles


def test_create_get_update_delete_camera() -> None:
    created = client.post("/cameras", json=TAPO)
    assert created.status_code == 201, created.text
    cam = created.json()
    assert cam["id"] == "front-door"
    assert cam["port"] == 554
    assert cam["effective_stream_path"] == "/stream2"
    assert cam["has_password"] is True
    assert "password" not in cam
    assert cam["masked_url"] == "rtsp://***:***@192.0.2.20:554/stream2"

    listed = client.get("/cameras").json()
    assert [c["id"] for c in listed] == ["front-door"]

    # Update without a password keeps the stored secret.
    updated = client.put(
        f"/cameras/{cam['id']}",
        json={**TAPO, "password": "", "stream_quality": "main", "name": "Front"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["has_password"] is True
    assert updated.json()["effective_stream_path"] == "/stream1"

    assert client.get(f"/cameras/{cam['id']}").json()["name"] == "Front"
    assert client.delete(f"/cameras/{cam['id']}").status_code == 204
    assert client.get(f"/cameras/{cam['id']}").status_code == 404
    assert client.delete(f"/cameras/{cam['id']}").status_code == 404


def test_password_is_encrypted_at_rest_and_never_returned() -> None:
    cam = client.post("/cameras", json=TAPO).json()
    db = sqlite3.connect(main_mod._store_path)
    row = db.execute("SELECT password_enc FROM cameras WHERE id = ?", (cam["id"],)).fetchone()
    db.close()
    assert row and row[0].startswith("enc:v1:")
    assert "s3cret-pass" not in row[0]
    body = client.get(f"/cameras/{cam['id']}").text
    assert "s3cret-pass" not in body
    # Audit rows must not carry the password either.
    db = sqlite3.connect(main_mod._store_path)
    audit = " ".join(r[0] for r in db.execute("SELECT payload_json FROM audit"))
    db.close()
    assert "s3cret-pass" not in audit


def test_enable_disable_round_trip() -> None:
    cam = client.post("/cameras", json=TAPO).json()
    off = client.post(f"/cameras/{cam['id']}/enabled", json={"enabled": False})
    assert off.status_code == 200 and off.json()["enabled"] is False
    assert client.get("/cameras").json()[0]["enabled"] is False
    on = client.post(f"/cameras/{cam['id']}/enabled", json={"enabled": True})
    assert on.json()["enabled"] is True


def test_validation_errors() -> None:
    assert client.post("/cameras", json={**TAPO, "profile": "nope"}).status_code == 422
    assert client.post("/cameras", json={**TAPO, "host": ""}).status_code == 422
    # Hikvision requires credentials.
    r = client.post("/cameras", json={"name": "h", "profile": "hikvision", "host": "192.0.2.3"})
    assert r.status_code == 422


def test_synthetic_and_webrtc_cameras_need_no_host() -> None:
    syn = client.post("/cameras", json={"name": "Demo", "profile": "synthetic"})
    assert syn.status_code == 201 and syn.json()["masked_url"] == ""
    web = client.post("/cameras", json={"name": "Laptop", "profile": "browser_webrtc"})
    assert web.status_code == 201


def test_test_connection_uses_probe_and_redacts(monkeypatch) -> None:
    captured: dict = {}

    def fake_probe(url: str, rtsp_transport: str) -> dict:
        captured["url"] = url
        return {"ok": False, "stage": "auth", "error": "Authentication failed", "masked_url": "x"}

    monkeypatch.setattr(cam_routes, "_probe_payload", fake_probe)
    r = client.post("/cameras/test", json=TAPO)
    assert r.status_code == 200 and r.json()["stage"] == "auth"
    assert captured["url"] == "rtsp://viewer:s3cret-pass@192.0.2.20:554/stream2"

    cam = client.post("/cameras", json=TAPO).json()
    r = client.post(f"/cameras/{cam['id']}/test")
    assert r.status_code == 200
    # Saved-camera probe rebuilt the credentialed URL from the encrypted store.
    assert captured["url"] == "rtsp://viewer:s3cret-pass@192.0.2.20:554/stream2"


def test_test_connection_url_stage_for_bad_config() -> None:
    r = client.post(
        "/cameras/test",
        json={"name": "h", "profile": "generic_rtsp", "host": "192.0.2.3", "stream_quality": "sub"},
    )
    # generic_rtsp with no creds is a valid URL; probing is mocked elsewhere, so just check shape
    assert r.status_code == 200 and "stage" in r.json()
