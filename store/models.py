"""Pydantic models for runtime configuration held in the SQLite config store."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from vision.camera_profiles import CAMERA_PROFILES, STREAM_QUALITIES, CameraConfigError, get_profile

ModelBackend = Literal["vllm", "ollama", "nim", "mock"]


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
        if profile.requires_host and not self.host:
            raise ValueError(f"host is required for {profile.label} cameras")
        if self.port is None and profile.requires_host:
            self.port = profile.default_port
        return self


class CameraRecord(BaseModel):
    """Camera row as returned by the API — never carries the password."""

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

    @property
    def source_kind(self) -> str:
        if self.profile in {"browser_webrtc", "synthetic"}:
            return self.profile
        return "stream"


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
