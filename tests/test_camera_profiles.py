import json

import pytest

from vision.camera_profiles import (
    CameraConfigError,
    build_camera_connection,
    ffplay_preview,
    verify_camera_connection,
)


def test_hikvision_profile_builds_rtsp_url_from_env(monkeypatch):
    monkeypatch.setenv("CAMERA_USERNAME", "operator")
    monkeypatch.setenv("CAMERA_PASSWORD", "pass word")

    connection = build_camera_connection(
        {
            "camera_id": "cam-north",
            "model_type": "hikvision",
            "host": "192.168.1.50",
            "channel": 1,
            "stream": "01",
            "username_env": "CAMERA_USERNAME",
            "password_env": "CAMERA_PASSWORD",
        }
    )

    assert connection.camera_id == "cam-north"
    assert connection.feed_url == (
        "rtsp://operator:pass%20word@192.168.1.50:554/Streaming/Channels/101"
    )
    assert connection.masked_feed_url == "rtsp://***:***@192.168.1.50:554/Streaming/Channels/101"


def test_tapo_profile_uses_stream_path(monkeypatch):
    monkeypatch.setenv("CAMERA_USERNAME", "test-user")
    monkeypatch.setenv("CAMERA_PASSWORD", "test-password")

    connection = build_camera_connection(
        {
            "camera_id": "tapo-local-example",
            "model_type": "tapo",
            "host": "192.168.1.50",
            "stream": "1",
            "username_env": "CAMERA_USERNAME",
            "password_env": "CAMERA_PASSWORD",
        }
    )

    assert connection.model_type == "tapo"
    assert connection.feed_url.endswith("@192.168.1.50:554/stream1")


def test_missing_credentials_fail_for_authenticated_camera():
    with pytest.raises(CameraConfigError, match="requires username and password"):
        build_camera_connection(
            {
                "model_type": "dahua",
                "host": "192.168.1.51",
            }
        )


def test_unsupported_camera_model_fails():
    with pytest.raises(CameraConfigError, match="Unsupported camera model_type"):
        build_camera_connection({"model_type": "unknown", "host": "192.168.1.52"})


def test_verify_camera_connection_can_skip_ffplay_check(tmp_path):
    config_path = tmp_path / "camera.json"
    config_path.write_text(
        json.dumps(
            {
                "model_type": "unifi_protect",
                "host": "192.168.1.53",
                "stream": "live",
            }
        ),
        encoding="utf-8",
    )

    connection = verify_camera_connection(config_path, require_ffplay=False)

    assert connection.feed_url == "rtsp://192.168.1.53:7447/live"


def test_ffplay_preview_adds_probe_options(monkeypatch):
    calls = []
    connection = build_camera_connection(
        {
            "model_type": "unifi_protect",
            "host": "192.168.1.53",
            "stream": "live",
        }
    )
    monkeypatch.setattr("subprocess.call", lambda command: calls.append(command) or 0)

    assert ffplay_preview(connection, seconds=5, no_display=True) == 0

    assert calls == [
        [
            "ffplay",
            "-nodisp",
            "-autoexit",
            "-t",
            "5",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-rtsp_transport",
            "tcp",
            "rtsp://192.168.1.53:7447/live",
        ]
    ]
