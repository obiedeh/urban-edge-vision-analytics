from __future__ import annotations

import pytest

from vision.camera_profiles import (
    CAMERA_PROFILES,
    CameraConfigError,
    build_camera_connection,
    get_profile,
    list_profiles,
)

REQUIRED = {
    "tapo", "hikvision", "dahua", "amcrest", "axis", "reolink", "unifi_protect",
    "generic_rtsp", "http_mjpeg", "browser_webrtc",
}


def test_all_required_profiles_present() -> None:
    assert REQUIRED <= set(CAMERA_PROFILES)
    assert {p["model_type"] for p in list_profiles()} >= REQUIRED


@pytest.mark.parametrize(
    "model_type,quality,expected",
    [
        ("tapo", "main", "rtsp://u:p@cam.local:554/stream1"),
        ("tapo", "sub", "rtsp://u:p@cam.local:554/stream2"),
        ("hikvision", "main", "rtsp://u:p@cam.local:554/Streaming/Channels/101"),
        ("hikvision", "sub", "rtsp://u:p@cam.local:554/Streaming/Channels/102"),
        ("dahua", "sub", "rtsp://u:p@cam.local:554/cam/realmonitor?channel=1&subtype=1"),
        ("amcrest", "main", "rtsp://u:p@cam.local:554/cam/realmonitor?channel=1&subtype=0"),
        ("axis", "main", "rtsp://u:p@cam.local:554/axis-media/media.amp"),
        ("reolink", "main", "rtsp://u:p@cam.local:554/h264Preview_01_main"),
        ("reolink", "sub", "rtsp://u:p@cam.local:554/h264Preview_01_sub"),
        ("http_mjpeg", "main", "http://u:p@cam.local:80/video"),
    ],
)
def test_profile_paths(model_type: str, quality: str, expected: str) -> None:
    profile = get_profile(model_type)
    url = profile.build_url("cam.local", "u", "p", None, quality=quality)
    assert url == expected


def test_stream_path_override_wins() -> None:
    url = get_profile("unifi_protect").build_url(
        "nvr.local", None, None, None, path="/AbCdEf123"
    )
    assert url == "rtsp://nvr.local:7447/AbCdEf123"


def test_credentials_are_url_quoted() -> None:
    url = get_profile("tapo").build_url("cam", "user@example.com", "p@ss w#rd", 554)
    assert url == "rtsp://user%40example.com:p%40ss%20w%23rd@cam:554/stream1"


def test_auth_required_profiles_reject_missing_credentials() -> None:
    with pytest.raises(CameraConfigError):
        get_profile("hikvision").build_url("cam", None, None, None)


def test_generic_rtsp_allows_no_credentials() -> None:
    assert get_profile("generic_rtsp").build_url("cam", None, None, None) == "rtsp://cam:554/stream"


def test_browser_webrtc_has_no_url() -> None:
    with pytest.raises(CameraConfigError):
        get_profile("browser_webrtc").build_url("x", None, None, None)


def test_unknown_profile() -> None:
    with pytest.raises(CameraConfigError):
        get_profile("nope")


def test_legacy_json_config_maps_stream_to_quality(monkeypatch) -> None:
    monkeypatch.setenv("CAM_PW", "secret")
    conn = build_camera_connection(
        {
            "camera_id": "front",
            "model_type": "tapo",
            "host": "192.0.2.10",
            "stream": "02",
            "username": "u",
            "password_env": "CAM_PW",
        }
    )
    assert conn.feed_url == "rtsp://u:secret@192.0.2.10:554/stream2"
    assert conn.masked_feed_url == "rtsp://***:***@192.0.2.10:554/stream2"
