from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote


class CameraConfigError(ValueError):
    """Raised when a camera configuration is incomplete or unsupported."""


@dataclass(frozen=True)
class CameraProfile:
    model_type: str
    default_port: int
    path_template: str
    protocol: str = "rtsp"
    requires_auth: bool = True

    def build_url(
        self,
        host: str,
        username: str | None,
        password: str | None,
        port: int | None,
        channel: int,
        stream: str,
        path: str | None = None,
    ) -> str:
        resolved_port = port or self.default_port
        feed_path = path or self.path_template.format(channel=channel, stream=stream)
        auth = ""
        if self.requires_auth:
            if not username or not password:
                raise CameraConfigError(
                    f"{self.model_type} requires username and password credentials."
                )
            auth = f"{quote(username, safe='')}:{quote(password, safe='')}@"
        return f"{self.protocol}://{auth}{host}:{resolved_port}{feed_path}"


CAMERA_PROFILES: dict[str, CameraProfile] = {
    "generic_rtsp": CameraProfile("generic_rtsp", 554, "/{stream}"),
    "hikvision": CameraProfile("hikvision", 554, "/Streaming/Channels/{channel}{stream}"),
    "dahua": CameraProfile(
        "dahua",
        554,
        "/cam/realmonitor?channel={channel}&subtype={stream}",
    ),
    "amcrest": CameraProfile(
        "amcrest",
        554,
        "/cam/realmonitor?channel={channel}&subtype={stream}",
    ),
    "axis": CameraProfile("axis", 554, "/axis-media/media.amp?streamprofile={stream}"),
    "reolink": CameraProfile(
        "reolink",
        554,
        "/h264Preview_{channel}_{stream}",
    ),
    "tapo": CameraProfile("tapo", 554, "/stream{stream}"),
    "unifi_protect": CameraProfile("unifi_protect", 7447, "/{stream}", requires_auth=False),
    "http_mjpeg": CameraProfile("http_mjpeg", 80, "/video", protocol="http"),
}


@dataclass(frozen=True)
class CameraConnection:
    camera_id: str
    model_type: str
    host: str
    feed_url: str
    ffplay_command: list[str]

    @property
    def masked_feed_url(self) -> str:
        return _mask_url(self.feed_url)


def _value_from_config_or_env(config: dict[str, Any], key: str) -> str | None:
    value = config.get(key)
    env_key = config.get(f"{key}_env")
    if value:
        return str(value)
    if env_key:
        return os.getenv(str(env_key))
    return None


def _mask_url(url: str) -> str:
    if "://" not in url or "@" not in url:
        return url
    protocol, rest = url.split("://", 1)
    _auth, tail = rest.split("@", 1)
    return f"{protocol}://***:***@{tail}"


def load_camera_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise CameraConfigError("Camera config must be a JSON object.")
    return data


def build_camera_connection(config: dict[str, Any]) -> CameraConnection:
    camera_id = str(config.get("camera_id", "cam-001"))
    model_type = str(config.get("model_type", "")).lower()
    if model_type not in CAMERA_PROFILES:
        supported = ", ".join(sorted(CAMERA_PROFILES))
        raise CameraConfigError(
            f"Unsupported camera model_type '{model_type}'. Supported: {supported}"
        )

    host = str(config.get("host", "")).strip()
    if not host:
        raise CameraConfigError("Camera host is required.")

    profile = CAMERA_PROFILES[model_type]
    username = _value_from_config_or_env(config, "username")
    password = _value_from_config_or_env(config, "password")
    port = int(config["port"]) if config.get("port") else None
    channel = int(config.get("channel", 1))
    stream = str(config.get("stream", "101"))
    path = str(config["path"]) if config.get("path") else None

    feed_url = profile.build_url(
        host=host,
        username=username,
        password=password,
        port=port,
        channel=channel,
        stream=stream,
        path=path,
    )
    ffplay_command = [
        "ffplay",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-rtsp_transport",
        str(config.get("rtsp_transport", "tcp")),
        feed_url,
    ]
    return CameraConnection(
        camera_id=camera_id,
        model_type=model_type,
        host=host,
        feed_url=feed_url,
        ffplay_command=ffplay_command,
    )


def verify_camera_connection(
    config_path: str | Path,
    require_ffplay: bool = True,
) -> CameraConnection:
    config = load_camera_config(config_path)
    connection = build_camera_connection(config)
    if require_ffplay and shutil.which("ffplay") is None:
        raise CameraConfigError(
            "ffplay was not found on PATH. Install ffmpeg to verify camera feeds."
        )
    return connection


def ffplay_preview(
    connection: CameraConnection,
    seconds: float | None = None,
    no_display: bool = False,
) -> int:
    command = connection.ffplay_command.copy()
    if seconds is not None:
        command[1:1] = ["-autoexit", "-t", str(seconds)]
    if no_display:
        command[1:1] = ["-nodisp"]
    return subprocess.call(command)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate an urban edge camera config and optionally preview it with ffplay.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", required=True, help="Path to camera JSON config.")
    parser.add_argument(
        "--print-url",
        action="store_true",
        help="Print the derived masked feed URL.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the ffplay command only.",
    )
    parser.add_argument(
        "--ffplay",
        action="store_true",
        help="Launch ffplay against the camera feed.",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="Limit ffplay preview duration.",
    )
    parser.add_argument(
        "--no-display",
        action="store_true",
        help="Run ffplay without opening a video window.",
    )
    parser.add_argument(
        "--skip-ffplay-check",
        action="store_true",
        help="Do not require ffplay to be installed during validation.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    connection = verify_camera_connection(
        args.config,
        require_ffplay=not args.skip_ffplay_check and (args.ffplay or args.dry_run),
    )
    print(f"camera_id={connection.camera_id}")
    print(f"model_type={connection.model_type}")
    print(f"host={connection.host}")
    if args.print_url or args.dry_run:
        print(f"feed_url={connection.masked_feed_url}")
    if args.dry_run:
        command = connection.ffplay_command.copy()
        command[-1] = connection.masked_feed_url
        print("ffplay_command=" + " ".join(command))
    if args.ffplay:
        raise SystemExit(
            ffplay_preview(connection, seconds=args.seconds, no_display=args.no_display)
        )


if __name__ == "__main__":
    main()
