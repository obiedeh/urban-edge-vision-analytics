"""Pasted RTSP links: parsing, credential stripping and redaction end to end."""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

import api.main as main_mod
from api.main import app
from api.routes import cameras as cam_routes
from store.models import CameraIn
from vision.camera_profiles import CameraConfigError
from vision.redaction import REDACTOR
from vision.rtsp_url import parse_rtsp_url, with_credentials

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_cameras():
    yield
    for cam in client.get("/cameras").json():
        client.delete(f"/cameras/{cam['id']}")


def test_parse_strips_embedded_credentials() -> None:
    parsed = parse_rtsp_url("rtsp://viewer:p%40ss%3Aword@192.0.2.9:8554/live/ch1?x=1#frag")
    assert parsed.scheme == "rtsp"
    assert parsed.host == "192.0.2.9"
    assert parsed.port == 8554
    assert parsed.path == "/live/ch1?x=1"
    assert parsed.username == "viewer"
    assert parsed.password == "p@ss:word"
    assert parsed.stripped_url == "rtsp://192.0.2.9:8554/live/ch1?x=1"
    assert parsed.has_credentials


def test_parse_without_credentials_and_default_ports() -> None:
    plain = parse_rtsp_url("  RTSP://cam.example.test/stream  ")
    assert plain.stripped_url == "rtsp://cam.example.test/stream"
    assert plain.port == 554 and not plain.has_credentials
    secure = parse_rtsp_url("rtsps://192.0.2.30:7441/AbC123")
    assert secure.scheme == "rtsps" and secure.port == 7441
    assert parse_rtsp_url("rtsps://192.0.2.30/x").port == 322


@pytest.mark.parametrize(
    "bad", ["", "http://192.0.2.9/stream", "rtsp://", "rtsp:///path", "rtsp://host:notaport/x"]
)
def test_parse_rejects_bad_links_without_echoing_them(bad: str) -> None:
    with pytest.raises(CameraConfigError) as exc:
        parse_rtsp_url(bad)
    assert "notaport" not in str(exc.value)


def test_with_credentials_round_trip_quotes_special_characters() -> None:
    url = with_credentials("rtsp://192.0.2.9:554/a?b=1", "us er", "p@ss/w:rd")
    assert url == "rtsp://us%20er:p%40ss%2Fw%3Ard@192.0.2.9:554/a?b=1"
    assert parse_rtsp_url(url).password == "p@ss/w:rd"
    assert with_credentials("rtsp://h/x", None, None) == "rtsp://h/x"


def test_camera_in_moves_link_credentials_into_fields() -> None:
    cam = CameraIn(name="Gate", profile="rtsp_url", source_url="rtsp://u:pw@192.0.2.9/s1")
    assert cam.source_url == "rtsp://192.0.2.9/s1"
    assert (cam.username, cam.password) == ("u", "pw")
    assert (cam.host, cam.port) == ("192.0.2.9", 554)
    # Typed fields win over the link's credentials.
    cam2 = CameraIn(
        name="Gate", profile="rtsp_url", source_url="rtsp://u:pw@192.0.2.9/s1",
        username="typed", password="typed-pw",
    )
    assert (cam2.username, cam2.password) == ("typed", "typed-pw")
    plain = CameraIn(name="Open", profile="rtsp_url", source_url="rtsps://192.0.2.30:7441/tok")
    assert plain.password == "" and plain.port == 7441
    with pytest.raises(ValueError, match="rtsp://"):
        CameraIn(name="Bad", profile="rtsp_url", source_url="http://192.0.2.9/s1")


def test_api_never_returns_or_stores_the_raw_link() -> None:
    raw = "rtsp://viewer:link-secret-9@192.0.2.9:8554/live/ch1"
    created = client.post(
        "/cameras", json={"name": "Pasted", "profile": "rtsp_url", "source_url": raw,
                          "enabled": False},
    )
    assert created.status_code == 201, created.text
    cam = created.json()
    assert cam["source_url"] == "rtsp://192.0.2.9:8554/live/ch1"
    assert cam["masked_url"] == "rtsp://***:***@192.0.2.9:8554/live/ch1"
    assert cam["username"] == "viewer" and cam["has_password"] is True
    assert cam["host"] == "192.0.2.9" and cam["port"] == 8554
    assert cam["connector"] == "rtsp_url" and cam["source_kind"] == "live_rtsp"
    assert "link-secret-9" not in created.text and "password" not in cam

    db = sqlite3.connect(main_mod._store_path)
    row = db.execute(
        "SELECT source_url, password_enc FROM cameras WHERE id = ?", (cam["id"],)
    ).fetchone()
    audit = " ".join(r[0] for r in db.execute("SELECT payload_json FROM audit"))
    db.close()
    assert row[0] == "rtsp://192.0.2.9:8554/live/ch1"
    assert row[1].startswith("enc:v1:") and "link-secret-9" not in row[1]
    assert "link-secret-9" not in audit

    # The runtime gets the credentialed URL back, and the redactor hides the secret.
    import asyncio

    url = asyncio.run(main_mod._config_store.feed_url(cam["id"]))
    assert url == raw
    assert "link-secret-9" not in REDACTOR.redact(f"failed opening {raw}")

    # Editing with a blank password keeps the stored one.
    updated = client.put(
        f"/cameras/{cam['id']}",
        json={"name": "Pasted", "profile": "rtsp_url",
              "source_url": "rtsp://192.0.2.9:8554/live/ch1", "username": "viewer",
              "password": "", "enabled": False},
    )
    assert updated.status_code == 200 and updated.json()["has_password"] is True
    assert asyncio.run(main_mod._config_store.feed_url(cam["id"])) == raw


def test_validation_error_for_a_bad_link_does_not_echo_it() -> None:
    bad = "http://viewer:oops-secret@192.0.2.9/not-rtsp"
    res = client.post("/cameras", json={"name": "Bad", "profile": "rtsp_url", "source_url": bad})
    assert res.status_code == 422
    assert "oops-secret" not in res.text
    assert "rtsp://" in res.json()["detail"][0]["msg"]


def test_test_endpoint_probes_pasted_link_with_stored_password(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def fake_probe(url: str, **kwargs):
        seen["url"] = url
        from vision.probe import ProbeResult

        return ProbeResult(ok=True, stage="ok", masked_url="masked")

    monkeypatch.setattr(cam_routes, "probe_stream", fake_probe)
    cam = client.post(
        "/cameras", json={"name": "Pasted", "profile": "rtsp_url",
                          "source_url": "rtsp://u:probe-secret@192.0.2.9/s1", "enabled": False},
    ).json()
    res = client.post(f"/cameras/{cam['id']}/test")
    assert res.status_code == 200 and res.json()["ok"] is True
    assert seen["url"] == "rtsp://u:probe-secret@192.0.2.9/s1"
    assert "probe-secret" not in res.text
    # Unsaved edit of the same address reuses the stored password.
    res = client.post(
        "/cameras/test",
        json={"name": "Pasted", "profile": "rtsp_url", "source_url": "rtsp://192.0.2.9/s1",
              "username": "u", "password": "", "camera_id": cam["id"]},
    )
    assert res.status_code == 200 and seen["url"] == "rtsp://u:probe-secret@192.0.2.9/s1"
    # A different host must not receive the stored password.
    res = client.post(
        "/cameras/test",
        json={"name": "Pasted", "profile": "rtsp_url", "source_url": "rtsp://192.0.2.10/s1",
              "username": "u", "password": "", "camera_id": cam["id"]},
    )
    assert res.json()["ok"] is False and "stored password" in res.json()["error"]
