"""Pydantic models for runtime configuration held in the SQLite config store.

``CameraIn`` is the create/update payload for every connector. Fields that a
connector does not use are left at their defaults, so a payload written for
the original vendor profiles is still valid unchanged:

* vendor profiles   host, port, username, password, stream_path/quality/channel
* ``rtsp_url``      source_url (credentials optional, embedded ones are stripped)
* ``usb``           device, capture_width, capture_height, capture_fps
* ``uploaded_video`` upload_id, playback
* ``browser_webrtc`` and ``synthetic`` need nothing else
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from vision.camera_profiles import (
    CAMERA_PROFILES,
    STREAM_QUALITIES,
    CameraConfigError,
    get_profile,
    source_kind_for,
)
from vision.rtsp_url import parse_rtsp_url

ModelBackend = Literal["vllm", "ollama", "nim", "mock"]
Playback = Literal["loop", "once"]
UploadSourceKind = Literal["recorded", "generated"]

_DEVICE_RE = re.compile(r"^/dev/video\d+$")
_UPLOAD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,120}$")


class CameraIn(BaseModel):
    """Create/update payload. ``password`` blank on update keeps the stored one."""

    name: str = Field(min_length=1, max_length=80)
    profile: str = "generic_rtsp"
    host: str = ""
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str = ""
    password: str = ""
    stream_path: str = ""
    stream_quality: str = "main"
    channel: int = Field(default=1, ge=1, le=64)
    rtsp_transport: Literal["tcp", "udp"] = "tcp"
    enabled: bool = True
    show_on_live: bool = True
    # rtsp_url: the pasted link. Stored and echoed without credentials.
    source_url: str = ""
    # usb: V4L2 device node and the requested capture mode (blank = driver default)
    device: str = ""
    capture_width: int | None = Field(default=None, ge=16, le=7680)
    capture_height: int | None = Field(default=None, ge=16, le=4320)
    capture_fps: float | None = Field(default=None, gt=0, le=240)
    capture_format: str = Field(default="", max_length=8)  # V4L2 fourcc, e.g. MJPG
    # uploaded_video: which upload to play and whether to loop it
    upload_id: str = ""
    playback: Playback = "loop"

    @model_validator(mode="after")
    def _validate(self) -> CameraIn:
        try:
            profile = get_profile(self.profile)
        except CameraConfigError as exc:
            raise ValueError(str(exc)) from exc
        self.profile = profile.model_type
        if self.stream_quality not in STREAM_QUALITIES:
            raise ValueError(f"stream_quality must be one of {STREAM_QUALITIES}")
        self.host = self.host.strip()
        self.stream_path = self.stream_path.strip()
        self.device = self.device.strip()
        self.capture_format = self.capture_format.strip().upper()
        self.upload_id = self.upload_id.strip()
        if profile.connector == "rtsp_url":
            self._apply_rtsp_url()
        elif profile.connector == "usb":
            if not _DEVICE_RE.match(self.device):
                raise ValueError("Choose a USB camera device (for example /dev/video0).")
            if (self.capture_width is None) != (self.capture_height is None):
                raise ValueError("capture_width and capture_height must be set together.")
        elif profile.connector == "upload":
            if not _UPLOAD_ID_RE.match(self.upload_id):
                raise ValueError("Choose an uploaded video to play.")
        if profile.requires_host and not self.host:
            raise ValueError(f"host is required for {profile.label} cameras")
        if self.port is None and profile.requires_host:
            self.port = profile.default_port
        return self

    def _apply_rtsp_url(self) -> None:
        """Strip credentials out of the pasted link into the username/password fields."""
        try:
            parsed = parse_rtsp_url(self.source_url)
        except CameraConfigError as exc:
            raise ValueError(str(exc)) from exc
        self.source_url = parsed.stripped_url
        self.host = parsed.host
        self.port = parsed.port
        self.stream_path = ""
        if parsed.has_credentials:
            # Fields typed by the operator win over credentials embedded in the link.
            self.username = self.username or parsed.username
            self.password = self.password or parsed.password


class UploadRecord(BaseModel):
    """An uploaded video file as returned by the API."""

    id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    source_kind: UploadSourceKind = "recorded"
    stored_name: str = ""
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    codec: str | None = None
    frames: int | None = None
    created_at: str | None = None
    # ids of cameras playing this upload (filled by the store)
    camera_ids: list[str] = Field(default_factory=list)


class CameraRecord(BaseModel):
    """Camera row as returned by the API — never carries the password or a raw link."""

    id: str
    name: str
    profile: str
    host: str = ""
    port: int | None = None
    username: str = ""
    has_password: bool = False
    stream_path: str = ""
    effective_stream_path: str = ""
    stream_quality: str = "main"
    channel: int = 1
    rtsp_transport: str = "tcp"
    enabled: bool = True
    show_on_live: bool = True
    masked_url: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    # connector details (defaults for the original vendor profiles)
    connector: str = "network"
    source_url: str = ""
    device: str = ""
    capture_width: int | None = None
    capture_height: int | None = None
    capture_fps: float | None = None
    capture_format: str = ""
    upload_id: str = ""
    playback: Playback = "loop"
    upload: UploadRecord | None = None
    source_kind: str = "live_rtsp"

    @staticmethod
    def source_kind_of(profile: str, upload_source_kind: str | None = None) -> str:
        return source_kind_for(profile, upload_source_kind)


class ModelSettings(BaseModel):
    backend: ModelBackend = "mock"
    endpoint: str = ""
    model: str = ""
    api_key: str = ""           # write-only; stored encrypted
    has_api_key: bool = False   # read-only echo
    think: bool = False
    max_tokens: int = Field(default=512, ge=32, le=8192)
    timeout_s: float = Field(default=60.0, ge=5, le=600)
    label: str = ""             # catalog label for display

    def normalized_endpoint(self) -> str:
        ep = self.endpoint.strip().rstrip("/")
        if not ep:
            ep = {
                "vllm": "http://localhost:8000",
                "ollama": "http://localhost:11434",
                "nim": "https://integrate.api.nvidia.com",
                "mock": "",
            }[self.backend]
        if ep and self.backend in {"vllm", "ollama", "nim"} and not ep.endswith("/v1"):
            ep = ep + "/v1"
        return ep


class InferenceSettings(BaseModel):
    interval_ms: int = Field(default=1000, ge=100, le=60000)
    width: int = Field(default=640, ge=160, le=1920)
    height: int = Field(default=360, ge=120, le=1080)
    prompt_preset: str = "traffic_detection"
    jpeg_quality: int = Field(default=80, ge=40, le=95)
    display_max_width: int = Field(default=1280, ge=320, le=3840)


class LiveSettings(BaseModel):
    """Which cameras the Live page shows (empty = all enabled cameras)."""

    camera_ids: list[str] = Field(default_factory=list)


def profile_catalog() -> list[dict[str, Any]]:
    return [p.to_dict() for p in CAMERA_PROFILES.values()]
