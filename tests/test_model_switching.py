"""Model selection: settings persistence, runtime hot-swap, API-key handling, preflight."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes import local_inference as li
from store.models import ModelSettings
from vision.adapters import MockDetectionAdapter, OpenAIVisionAdapter
from vision.host_capabilities import HostCapabilities, default_model_for
from vision.model_runtime import ModelRuntime, build_adapter

client = TestClient(app)


def test_build_adapter_switches_backend() -> None:
    assert isinstance(build_adapter(ModelSettings(backend="mock")), MockDetectionAdapter)
    adapter = build_adapter(
        ModelSettings(
            backend="vllm", endpoint="http://localhost:8001", model="nvidia/cosmos-reason2-2b"
        )
    )
    assert isinstance(adapter, OpenAIVisionAdapter)
    assert adapter.endpoint == "http://localhost:8001/v1"
    ollama = build_adapter(ModelSettings(backend="ollama", model="gemma4:e4b"))
    assert isinstance(ollama, OpenAIVisionAdapter)
    assert ollama.endpoint == "http://localhost:11434/v1"


def test_runtime_configure_hot_swaps_adapter() -> None:
    rt = ModelRuntime(ModelSettings(backend="mock"))
    first = rt.adapter
    rt.configure(ModelSettings(backend="vllm", model="m", endpoint="http://localhost:8000"))
    assert rt.adapter is not first
    assert rt.settings.backend == "vllm"
    assert rt.status()["endpoint"] == "http://localhost:8000/v1"


def test_put_model_settings_persists_and_masks_api_key() -> None:
    body = {
        "backend": "nim",
        "endpoint": "https://integrate.api.nvidia.com",
        "model": "nvidia/cosmos-reason2-8b",
        "api_key": "nvapi-SECRET",
    }
    r = client.put("/settings/model", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["has_api_key"] is True
    assert data["api_key"] == ""
    assert "nvapi-SECRET" not in r.text
    again = client.get("/settings/model").json()
    assert again["model"] == "nvidia/cosmos-reason2-8b" and again["has_api_key"] is True
    # Blank api_key on a later save keeps the stored key.
    r2 = client.put("/settings/model", json={**body, "api_key": "", "model": "x"})
    assert r2.json()["has_api_key"] is True
    client.put("/settings/model", json={"backend": "mock"})


def test_apply_endpoint_switches_running_model() -> None:
    r = client.post(
        "/inference/apply",
        json={"backend": "ollama", "model": "gemma4:e4b", "endpoint": "http://localhost:11434"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["runtime"]["backend"] == "ollama"
    assert r.json()["runtime"]["model"] == "gemma4:e4b"
    assert client.get("/runtime/status").json()["model"]["endpoint"] == "http://localhost:11434/v1"
    client.post("/inference/apply", json={"backend": "mock", "model": ""})


def test_inference_settings_round_trip() -> None:
    r = client.put(
        "/settings/inference",
        json={"interval_ms": 500, "width": 800, "height": 450, "prompt_preset": "congestion"},
    )
    assert r.status_code == 200, r.text
    assert client.get("/settings/inference").json()["interval_ms"] == 500
    assert client.get("/runtime/status").json()["inference"]["prompt_preset"] == "congestion"
    bad = client.put("/settings/inference", json={"prompt_preset": "nope"})
    assert bad.status_code == 422
    client.put("/settings/inference", json={})


def _caps(**kw) -> HostCapabilities:
    base = dict(
        hostname="h", machine="x86_64", is_jetson=False, jetson_model=None,
        gpu_name="NVIDIA GeForce RTX 5090", gpu_vram_total_gb=32.0, gpu_vram_free_gb=30.0,
        ram_total_gb=128.0, ram_available_gb=100.0, unified_memory=False, has_docker=True,
        has_vllm_binary=True, has_ollama=True, recommended_profile="workstation-gpu",
    )
    base.update(kw)
    return HostCapabilities(**base)


def test_environment_default_model() -> None:
    thor = _caps(is_jetson=True, jetson_model="NVIDIA Jetson AGX Thor", machine="aarch64",
                 unified_memory=True, gpu_vram_total_gb=None, gpu_vram_free_gb=None)
    assert default_model_for(thor)["model"] == "nvidia/cosmos-reason2-2b"
    assert default_model_for(thor)["backend"] == "vllm"
    ws = _caps()
    assert default_model_for(ws)["model"] == "gemma4:e4b"
    assert default_model_for(ws)["backend"] == "ollama"
    assert default_model_for(_caps(gpu_name=None))["backend"] == "mock"


def test_catalog_preflight_flags_models_that_do_not_fit(monkeypatch) -> None:
    monkeypatch.setattr(li, "detect_host", lambda: _caps(gpu_vram_free_gb=14.0))
    models = {m["name"]: m for m in client.get("/inference/catalog").json()["models"]}
    assert models["gemma4:e4b"]["can_run"] is True
    assert models["gemma4:31b"]["can_run"] is False
    assert "needs ~28 GB" in models["gemma4:31b"]["blocked_reasons"][0]
    assert models["gemma4:e4b"]["recommended"] is True


def test_catalog_on_jetson_uses_available_ram_and_docker(monkeypatch) -> None:
    thor = _caps(is_jetson=True, machine="aarch64", unified_memory=True,
                 gpu_vram_total_gb=None, gpu_vram_free_gb=None, ram_available_gb=110.0,
                 has_vllm_binary=False, has_ollama=False)
    monkeypatch.setattr(li, "detect_host", lambda: thor)
    models = {m["name"]: m for m in client.get("/inference/catalog").json()["models"]}
    cosmos = models["nvidia/cosmos-reason2-2b"]
    assert cosmos["recommended"] and cosmos["can_run"] and cosmos["launcher"] == "docker"
    assert models["nvidia/cosmos3-nano-reasoner"]["can_run"] is False


def test_vllm_preflight_rejects_when_unified_memory_too_small() -> None:
    from fastapi import HTTPException

    thor = _caps(is_jetson=True, unified_memory=True, ram_available_gb=4.0)
    with pytest.raises(HTTPException) as exc:
        li._ensure_vllm_memory_available({"hf_id": "x", "vram_gb": 18}, thor)
    assert exc.value.status_code == 409


def test_jetson_docker_launch_shape() -> None:
    req = li.VllmStartRequest(model="nvidia/cosmos-reason2-2b", model_path="/tmp/models/c2b")
    launch = li._jetson_launch(li._find_vllm_catalog_entry(req.model), req)
    assert launch.model_path == "/tmp/models/c2b"
    assert launch.served_model_name == "nvidia/cosmos-reason2-2b"
    assert launch.gpu_memory_utilization == 0.25
    assert "--reasoning-parser" not in launch.extra_args


def test_vllm_stop_requires_confirm_and_logs_event() -> None:
    assert client.post("/inference/vllm/stop", json={}).status_code == 409
    r = client.post("/inference/vllm/stop", json={"confirm": True, "reason": "test"})
    assert r.status_code == 200 and r.json()["state"] == "stopped"
    events = client.get("/runtime/status").json()["server_events"]
    assert events and events[-1]["kind"] == "stopped by operator"
    assert events[-1]["reason"] == "test"


def test_run_capture_preflight_refuses_mock_or_missing_camera(monkeypatch) -> None:
    import httpx

    from telemetry import run_capture

    class _Client:
        def get(self, path: str, **kw):  # noqa: ANN001
            return client.get(path)

    client.post("/inference/apply", json={"backend": "mock", "model": ""})
    with pytest.raises(SystemExit, match="not running"):
        run_capture.preflight(_Client(), "no-such-camera")  # type: ignore[arg-type]
    cam = client.post("/cameras", json={"name": "Preflight", "profile": "synthetic"}).json()
    try:
        # The TestClient app never ran its lifespan, so the session is absent: not streaming.
        with pytest.raises(SystemExit):
            run_capture.preflight(_Client(), cam["id"])  # type: ignore[arg-type]
        # A streaming camera with a mock backend is still refused.
        monkeypatch.setattr(
            _Client, "get",
            lambda self, path, **kw: httpx.Response(
                200,
                json={
                    "cameras": [{"camera_id": cam["id"], "state": "streaming"}],
                    "model": {"backend": "mock", "model": "", "endpoint": "", "state": "idle"},
                },
            ),
        )
        with pytest.raises(SystemExit, match="mock"):
            run_capture.preflight(_Client(), cam["id"])  # type: ignore[arg-type]
    finally:
        client.delete(f"/cameras/{cam['id']}")
