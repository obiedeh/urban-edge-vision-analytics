"""Camera vendor profiles: default ports and main/sub stream paths.

A profile turns ``host + port + credentials + quality`` into a feed URL. The
stream path is auto-filled from the profile and may be overridden per camera
(``stream_path``), which is how UniFi Protect's per-camera token path and odd
firmware variants are handled.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from vision.redaction import mask_url


class CameraConfigError(ValueError):
    """Raised when a camera configuration is incomplete or unsupported."""


@dataclass(frozen=True)
class CameraProfile:
    model_type: str
    label: str
    default_port: int
    main_path: str
    sub_path: str
    protocol: str = "rtsp"
    requires_auth: bool = True
    requires_host: bool = True
    notes: str = ""

    def stream_path(self, quality: str = "main", channel: int = 1) -> str:
        template = self.main_path if quality != "sub" else self.sub_path
        return template.format(channel=channel, channel2=f"{channel:02d}")

    def build_url(
        self,
        host: str,
        username: str | None,
        password: str | None,
        port: int | None = None,
        *,
        channel: int = 1,
        quality: str = "main",
        path: str | None = None,
    ) -> str:
        if not self.requires_host:
            raise CameraConfigError(f"{self.label} cameras have no stream URL.")
        host = (host or "").strip()
        if not host:
            raise CameraConfigError("Camera host is required.")
        resolved_port = port or self.default_port
        feed_path = (path or "").strip() or self.stream_path(quality, channel)
        if not feed_path.startswith("/"):
            feed_path = "/" + feed_path
        auth = ""
        if username or password:
            auth = f"{quote(username or '', safe='')}:{quote(password or '', safe='')}@"
        elif self.requires_auth:
            raise CameraConfigError(f"{self.label} requires a username and password.")
        return f"{self.protocol}://{auth}{host}:{resolved_port}{feed_path}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["example_main_path"] = self.stream_path("main")
        data["example_sub_path"] = self.stream_path("sub")
        return data


CAMERA_PROFILES: dict[str, CameraProfile] = {
    "tapo": CameraProfile(
        "tapo", "TP-Link Tapo", 554, "/stream1", "/stream2",
        notes="Create a camera account in the Tapo app (Advanced Settings > Camera Account).",
    ),
    "hikvision": CameraProfile(
        "hikvision", "Hikvision", 554,
        "/Streaming/Channels/{channel}01", "/Streaming/Channels/{channel}02",
    ),
    "dahua": CameraProfile(
        "dahua", "Dahua", 554,
        "/cam/realmonitor?channel={channel}&subtype=0",
        "/cam/realmonitor?channel={channel}&subtype=1",
    ),
    "amcrest": CameraProfile(
        "amcrest", "Amcrest", 554,
        "/cam/realmonitor?channel={channel}&subtype=0",
        "/cam/realmonitor?channel={channel}&subtype=1",
    ),
    "axis": CameraProfile(
        "axis", "Axis", 554,
        "/axis-media/media.amp", "/axis-media/media.amp?resolution=640x480",
    ),
    "reolink": CameraProfile(
        "reolink", "Reolink", 554,
        "/h264Preview_{channel2}_main", "/h264Preview_{channel2}_sub",
    ),
    "unifi_protect": CameraProfile(
        "unifi_protect", "UniFi Protect", 7447, "/{channel}", "/{channel}",
        requires_auth=False,
        notes="Paste the RTSPS/RTSP stream token from Protect as the stream path.",
    ),
    "generic_rtsp": CameraProfile(
        "generic_rtsp", "Generic RTSP", 554, "/stream", "/stream",
        requires_auth=False, notes="Edit the stream path to match the camera.",
    ),
    "http_mjpeg": CameraProfile(
        "http_mjpeg", "HTTP MJPEG", 80, "/video", "/video",
        protocol="http", requires_auth=False,
    ),
    "browser_webrtc": CameraProfile(
        "browser_webrtc", "Browser webcam (WebRTC)", 0, "", "",
        requires_auth=False, requires_host=False,
        notes="The operator's browser shares its webcam to this camera slot.",
    ),
    "synthetic": CameraProfile(
        "synthetic", "Synthetic test feed", 0, "", "",
        requires_auth=False, requires_host=False,
        notes="Generated frames for demos and tests. Labelled synthetic everywhere.",
    ),
}

STREAM_QUALITIES = ("main", "sub")


def list_profiles() -> list[dict[str, Any]]:
    return [p.to_dict() for p in CAMERA_PROFILES.values()]


def get_profile(model_type: str) -> CameraProfile:
    key = (model_type or "").strip().lower()
    if key not in CAMERA_PROFILES:
        supported = ", ".join(sorted(CAMERA_PROFILES))
        raise CameraConfigError(
            f"Unsupported camera model_type '{model_type}'. Supported: {supported}"
        )
    return CAMERA_PROFILES[key]


# ── Legacy JSON-config path (kept for the CLI and for importing old configs) ───


@dataclass(frozen=True)
class CameraConnection:
    camera_id: str
    model_type: str
    host: str
    feed_url: str

    @property
    def masked_feed_url(self) -> str:
        return mask_url(self.feed_url)


def _value_from_config_or_env(config: dict[str, Any], key: str) -> str | None:
    value = config.get(key)
    env_key = config.get(f"{key}_env")
    if value:
        return str(value)
    if env_key:
        return os.getenv(str(env_key))
    return None


def _legacy_quality(stream: Any) -> str:
    """Map the old free-text ``stream`` field onto main/sub."""
    text = str(stream or "").strip().lower()
    return "sub" if text in {"2", "02", "102", "sub", "substream", "low"} else "main"


def load_camera_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise CameraConfigError("Camera config must be a JSON object.")
    return data


def build_camera_connection(config: dict[str, Any]) -> CameraConnection:
    camera_id = str(config.get("camera_id", "cam-001"))
    profile = get_profile(str(config.get("model_type", "")))
    host = str(config.get("host", "")).strip()
    feed_url = profile.build_url(
        host=host,
        username=_value_from_config_or_env(config, "username"),
        password=_value_from_config_or_env(config, "password"),
        port=int(config["port"]) if config.get("port") else None,
        channel=int(config.get("channel", 1)),
        quality=str(config.get("stream_quality") or _legacy_quality(config.get("stream"))),
        path=str(config["path"]) if config.get("path") else None,
    )
    return CameraConnection(
        camera_id=camera_id, model_type=profile.model_type, host=host, feed_url=feed_url
    )


def verify_camera_connection(config_path: str | Path) -> CameraConnection:
    return build_camera_connection(load_camera_config(config_path))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a camera JSON config and print its masked feed URL.",
    )
    parser.add_argument("--config", required=True, help="Path to camera JSON config.")
    parser.add_argument("--probe", action="store_true", help="Decode one frame from the feed.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    connection = verify_camera_connection(args.config)
    print(f"camera_id={connection.camera_id}")
    print(f"model_type={connection.model_type}")
    print(f"host={connection.host}")
    print(f"feed_url={connection.masked_feed_url}")
    if args.probe:
        from vision.probe import probe_stream

        result = probe_stream(connection.feed_url)
        print(f"probe_ok={result.ok} stage={result.stage} error={result.error or ''}")
        if result.ok:
            print(f"resolution={result.width}x{result.height} codec={result.codec}")


if __name__ == "__main__":
    main()
