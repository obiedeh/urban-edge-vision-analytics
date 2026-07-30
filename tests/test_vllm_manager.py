import pytest

from api.vllm_manager import VllmServerManager, parse_local_vllm_endpoint


def test_parse_local_vllm_endpoint_defaults_to_localhost_8000():
    endpoint = parse_local_vllm_endpoint()

    assert endpoint.base_url == "http://localhost:8000"
    assert endpoint.api_url == "http://localhost:8000/v1"
    assert endpoint.port == 8000


def test_parse_local_vllm_endpoint_strips_v1_suffix():
    endpoint = parse_local_vllm_endpoint("http://127.0.0.1:8001/v1")

    assert endpoint.base_url == "http://127.0.0.1:8001"
    assert endpoint.api_url == "http://127.0.0.1:8001/v1"
    assert endpoint.port == 8001


def test_parse_local_vllm_endpoint_rejects_remote_hosts():
    with pytest.raises(ValueError, match="local endpoints"):
        parse_local_vllm_endpoint("http://example.com:8000")


def test_start_launches_vllm_and_returns_starting_status(monkeypatch):
    commands = []

    class FakeProc:
        pid = 4242
        stdout = []

        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return None

    monkeypatch.setattr("api.vllm_manager.shutil.which", lambda name: "/tmp/vllm")
    monkeypatch.setattr(
        "api.vllm_manager.subprocess.Popen",
        lambda command, **kwargs: commands.append((command, kwargs)) or FakeProc(),
    )

    manager = VllmServerManager()
    status = manager.start(
        model=" nvidia/cosmos3-nano-reasoner ",
        endpoint="http://localhost:8001/v1",
        extra_args=["--trust-remote-code"],
        extra_env={"NIM_MODEL_SIZE": "nano"},
    )

    assert status["state"] == "starting"
    assert status["pid"] == 4242
    assert status["model"] == "nvidia/cosmos3-nano-reasoner"
    assert status["endpoint"] == "http://localhost:8001/v1"
    assert commands[0][0] == [
        "/tmp/vllm",
        "serve",
        "nvidia/cosmos3-nano-reasoner",
        "--host",
        "0.0.0.0",
        "--port",
        "8001",
        "--trust-remote-code",
    ]
    assert commands[0][1]["env"]["NIM_MODEL_SIZE"] == "nano"


def test_start_can_launch_vllm_omni(monkeypatch):
    commands = []

    class FakeProc:
        pid = 4343
        stdout = []

        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return None

    monkeypatch.setattr(
        "api.vllm_manager.shutil.which",
        lambda name: f"/tmp/{name}" if name == "vllm-omni" else None,
    )
    monkeypatch.setattr(
        "api.vllm_manager.subprocess.Popen",
        lambda command, **kwargs: commands.append((command, kwargs)) or FakeProc(),
    )

    manager = VllmServerManager()
    status = manager.start(
        model="nvidia/Cosmos3-Nano",
        endpoint="http://localhost:8000",
        extra_args=["--omni"],
        executable="vllm-omni",
    )

    assert status["state"] == "starting"
    assert commands[0][0][:3] == ["/tmp/vllm-omni", "serve", "nvidia/Cosmos3-Nano"]
    assert "--omni" in commands[0][0]


def test_stop_without_managed_process_is_noop():
    manager = VllmServerManager()

    status = manager.stop()

    assert status["state"] == "stopped"
    assert status["pid"] is None
