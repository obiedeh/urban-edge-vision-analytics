import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from api.config import CloudSettings, Settings, load_settings

REPO = Path(__file__).resolve().parent.parent


def test_default_local_config_loads_with_cloud_disabled():
    settings = load_settings(REPO / "configs" / "local.json", env={})
    assert settings.detection_adapter == "mock"
    assert settings.cameras[0].camera_id == "cam-001"
    assert settings.cloud.enabled is False
    assert settings.cloud.publisher == "null"


def test_jetson_config_loads():
    settings = load_settings(REPO / "configs" / "jetson.json", env={})
    assert settings.detection_adapter == "onnx"
    assert settings.detection_model == "yolov8n.onnx"
    assert settings.cameras[0].source_type == "rtsp"
    assert settings.cloud.enabled is False


def test_missing_default_file_falls_back_to_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no configs/local.json here
    settings = load_settings(env={})
    assert settings == Settings()
    assert settings.cloud == CloudSettings()


def test_missing_explicit_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "nope.json", env={})
    with pytest.raises(FileNotFoundError):
        load_settings(env={"URBAN_EDGE_CONFIG": str(tmp_path / "nope.json")})


def test_env_config_path_is_used(tmp_path):
    cfg = tmp_path / "custom.json"
    cfg.write_text(json.dumps({"api_port": 9999}))
    settings = load_settings(env={"URBAN_EDGE_CONFIG": str(cfg)})
    assert settings.api_port == 9999


def test_env_overrides_cloud_section(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"cloud": {"enabled": False, "thing_name": "from-file"}}))
    settings = load_settings(
        cfg,
        env={
            "URBAN_EDGE_CLOUD_ENABLED": "true",
            "URBAN_EDGE_CLOUD_PUBLISHER": "file",
            "URBAN_EDGE_CLOUD_FILE_PATH": "/tmp/out.jsonl",
            "URBAN_EDGE_CLOUD_SCHEMA_VERSION": "2",
        },
    )
    assert settings.cloud.enabled is True
    assert settings.cloud.publisher == "file"
    assert settings.cloud.file_path == "/tmp/out.jsonl"
    assert settings.cloud.thing_name == "from-file"
    assert settings.cloud.schema_version == 2


@pytest.mark.parametrize("raw", ["0", "false", "no", "", "off"])
def test_env_enabled_falsy_values(tmp_path, raw):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"cloud": {"enabled": True}}))
    settings = load_settings(cfg, env={"URBAN_EDGE_CLOUD_ENABLED": raw})
    # Empty string means "unset": keep the file's value.
    assert settings.cloud.enabled is (raw == "")


def test_unknown_keys_are_rejected(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"cloud": {"publsher": "file"}}))
    with pytest.raises(ValidationError):
        load_settings(cfg, env={})


def test_unknown_publisher_is_rejected(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"cloud": {"publisher": "mqtt"}}))
    with pytest.raises(ValidationError):
        load_settings(cfg, env={})


def test_telemetry_interval_default_and_validation(tmp_path):
    assert CloudSettings().telemetry_interval_s == 30.0
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"cloud": {"telemetry_interval_s": 0}}))
    with pytest.raises(ValidationError):
        load_settings(cfg, env={})


def test_iot_core_settings_from_env(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"cloud": {"enabled": True, "publisher": "iot_core"}}))
    settings = load_settings(
        cfg,
        env={
            "URBAN_EDGE_CLOUD_IOT_ENDPOINT": "x-ats.iot.us-east-1.amazonaws.com",
            "URBAN_EDGE_CLOUD_CERT_PATH": "/etc/urban-edge/device.pem.crt",
            "URBAN_EDGE_CLOUD_KEY_PATH": "/etc/urban-edge/private.pem.key",
            "URBAN_EDGE_CLOUD_CA_PATH": "/etc/urban-edge/AmazonRootCA1.pem",
        },
    )
    assert settings.cloud.publisher == "iot_core"
    assert settings.cloud.iot_endpoint == "x-ats.iot.us-east-1.amazonaws.com"
    assert settings.cloud.cert_path == "/etc/urban-edge/device.pem.crt"
    assert settings.cloud.key_path == "/etc/urban-edge/private.pem.key"
    assert settings.cloud.ca_path == "/etc/urban-edge/AmazonRootCA1.pem"
