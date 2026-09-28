"""Application settings loaded from ``configs/*.json`` with env overrides.

Resolution order (highest wins):

1. ``URBAN_EDGE_CLOUD_*`` environment variables (cloud section only)
2. the JSON file named by ``URBAN_EDGE_CONFIG`` (or ``configs/local.json``)
3. model defaults

The edge app must run with no config file, no network and no AWS account, so
a missing *default* file falls back to defaults; a missing file that was
named explicitly via ``URBAN_EDGE_CONFIG`` is an error.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("configs/local.json")
CONFIG_PATH_ENV = "URBAN_EDGE_CONFIG"

PublisherKind = Literal["null", "file"]


class CameraSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera_id: str
    source_type: str = "synthetic"
    source_uri: str | None = None
    width: int = 1920
    height: int = 1080
    fps: float = 10


class CloudSettings(BaseModel):
    """Edge-to-cloud publishing. Off by default; the app never needs it."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    publisher: PublisherKind = "null"
    file_path: str | None = None
    thing_name: str = "urban-edge-local"
    schema_version: int = 1
    telemetry_interval_s: float = Field(default=30.0, gt=0)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detection_adapter: str = "mock"
    detection_model: str | None = None
    api_host: str = "127.0.0.1"
    api_port: int = 8080
    congestion_threshold: int = 10
    flow_window_size: int = 30
    cameras: list[CameraSettings] = Field(default_factory=list)
    cloud: CloudSettings = Field(default_factory=CloudSettings)


_CLOUD_ENV_KEYS: dict[str, str] = {
    "URBAN_EDGE_CLOUD_ENABLED": "enabled",
    "URBAN_EDGE_CLOUD_PUBLISHER": "publisher",
    "URBAN_EDGE_CLOUD_FILE_PATH": "file_path",
    "URBAN_EDGE_CLOUD_THING_NAME": "thing_name",
    "URBAN_EDGE_CLOUD_SCHEMA_VERSION": "schema_version",
    "URBAN_EDGE_CLOUD_TELEMETRY_INTERVAL_S": "telemetry_interval_s",
}

_TRUTHY = {"1", "true", "yes", "on"}


def _cloud_env_overrides(env: dict[str, str]) -> dict[str, object]:
    overrides: dict[str, object] = {}
    for env_key, field in _CLOUD_ENV_KEYS.items():
        raw = env.get(env_key)
        if raw is None or raw == "":
            continue
        if field == "enabled":
            overrides[field] = raw.strip().lower() in _TRUTHY
        else:
            overrides[field] = raw
    return overrides


def load_settings(
    path: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> Settings:
    """Load and validate settings.

    ``path`` wins over ``URBAN_EDGE_CONFIG``, which wins over the default file.
    ``env`` defaults to ``os.environ`` and is injectable for tests.
    """
    env = dict(os.environ) if env is None else env
    explicit = path is not None or bool(env.get(CONFIG_PATH_ENV))
    config_path = Path(path or env.get(CONFIG_PATH_ENV) or DEFAULT_CONFIG_PATH)

    raw: dict[str, object] = {}
    if config_path.exists():
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        logger.info("Loaded settings from %s", config_path)
    elif explicit:
        raise FileNotFoundError(f"Config file not found: {config_path}")
    else:
        logger.warning("Config file %s not found; using defaults", config_path)

    cloud_raw = dict(raw.get("cloud") or {})  # type: ignore[call-overload]
    cloud_raw.update(_cloud_env_overrides(env))
    raw["cloud"] = cloud_raw
    return Settings.model_validate(raw)
