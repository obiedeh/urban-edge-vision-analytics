"""App-managed local model server (vLLM) — binary or Docker launch.

On a workstation ``vllm serve`` runs from the venv. On Jetson the supported
path is NVIDIA's vLLM container, so the manager can also run
``docker run ... <image> vllm serve ...`` with the model directory mounted.
Either way the process is owned by this API: start, stop, status, log tail.
Nothing outside this manager (Isaac Sim, Ollama, other containers) is touched.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

MAX_LOG_LINES = 1000


@dataclass(frozen=True)
class VllmEndpoint:
    base_url: str
    api_url: str
    port: int


@dataclass(frozen=True)
class DockerLaunch:
    image: str
    model_path: str                  # host path to the model directory
    served_model_name: str
    container_name: str = "urban-edge-vllm"
    gpu_memory_utilization: float = 0.25
    max_model_len: int = 8192
    extra_args: tuple[str, ...] = ()
    cache_dir: str = "~/.cache/vllm"


class VllmServerManager:
    """Owns a single local vLLM server process started by this API."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None
        self._model: str | None = None
        self._endpoint: VllmEndpoint | None = None
        self._started_at: float | None = None
        self._log_tail: list[str] = []
        self._lock = threading.RLock()
        self._launcher: str = "binary"
        self._container_name: str | None = None
        self._reasoning_parser: str | None = None

    # ── binary launch ─────────────────────────────────────────────────────────

    def start(
        self,
        *,
        model: str,
        endpoint: str | None = None,
        extra_args: Sequence[str] | None = None,
        extra_env: Mapping[str, str] | None = None,
        executable: str | None = None,
    ) -> dict:
        selected_model = model.strip()
        if not selected_model:
            raise ValueError("model is required")

        selected_endpoint = parse_local_vllm_endpoint(endpoint)
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                if self._model == selected_model and self._endpoint == selected_endpoint:
                    return self.status()
                self._stop_locked()

            executable_name = executable or "vllm"
            env_var = f"{executable_name.upper().replace('-', '_')}_BIN"
            vllm_bin = (
                os.getenv(env_var)
                or (os.getenv("VLLM_BIN") if executable_name == "vllm" else None)
                or shutil.which(executable_name)
            )
            if not vllm_bin:
                raise FileNotFoundError(
                    f"{executable_name} executable was not found. "
                    f"Set {env_var} or install {executable_name}."
                )

            args = list(extra_args or [])
            command = [
                vllm_bin,
                "serve",
                selected_model,
                "--host",
                "127.0.0.1",
                "--port",
                str(selected_endpoint.port),
                *args,
            ]
            env = {
                **os.environ,
                "PYTHONUNBUFFERED": "1",
                **{k: str(v) for k, v in (extra_env or {}).items()},
            }
            self._launch(command, env, selected_model, selected_endpoint, "binary", args)
            return self.status()

    # ── docker launch ─────────────────────────────────────────────────────────

    def start_docker(
        self,
        *,
        launch: DockerLaunch,
        endpoint: str | None = None,
    ) -> dict:
        selected_endpoint = parse_local_vllm_endpoint(endpoint)
        docker = shutil.which("docker")
        if not docker:
            raise FileNotFoundError("docker executable was not found on this host.")
        model_dir = Path(os.path.expanduser(launch.model_path))
        if not model_dir.exists():
            raise FileNotFoundError(f"Model directory {model_dir} does not exist.")
        with self._lock:
            if self._launcher == "docker" and _container_running(launch.container_name):
                if self._model == launch.served_model_name and self._endpoint == selected_endpoint:
                    return self.status()
                self._stop_locked()
            elif self._proc is not None and self._proc.poll() is None:
                self._stop_locked()
            # Remove a stale container with the same name (exited earlier run).
            subprocess.run(
                [docker, "rm", "-f", launch.container_name], capture_output=True, check=False
            )
            cache_dir = Path(os.path.expanduser(launch.cache_dir))
            cache_dir.mkdir(parents=True, exist_ok=True)
            mount_point = f"/models/{model_dir.name}"
            args = list(launch.extra_args)
            # Detached: the model server may be shared with another app on the
            # device and must outlive an API restart (see detach()).
            command = [
                docker, "run", "-d", "--rm", "--name", launch.container_name,
                "--runtime", "nvidia", "--network", "host", "--ipc", "host",
                "-v", f"{model_dir}:{mount_point}",
                "-v", f"{cache_dir}:/root/.cache/vllm",
                launch.image,
                "vllm", "serve", mount_point,
                "--served-model-name", launch.served_model_name,
                "--host", "0.0.0.0",
                "--port", str(selected_endpoint.port),
                "--gpu-memory-utilization", str(launch.gpu_memory_utilization),
                "--max-model-len", str(launch.max_model_len),
                *args,
            ]
            launched = subprocess.run(command, capture_output=True, text=True, check=False)
            if launched.returncode != 0:
                raise RuntimeError(f"docker run failed: {launched.stderr.strip()[:300]}")
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            self._launch(
                [docker, "logs", "-f", launch.container_name], env, launch.served_model_name,
                selected_endpoint, "docker", args, container_name=launch.container_name,
            )
            self._log_tail.insert(0, " ".join(command))
            return self.status()

    def adopt_container(self, container_name: str, endpoint: str | None = None) -> bool:
        """Adopt a running container launched by an earlier API process."""
        docker = shutil.which("docker")
        if not docker or not _container_running(container_name):
            return False
        probe = subprocess.run(
            [docker, "inspect", "--format", "{{join .Config.Cmd \" \"}}", container_name],
            capture_output=True, text=True, check=False,
        )
        args = probe.stdout.split()
        model = _arg_after(args, "--served-model-name") or "unknown"
        port = _arg_after(args, "--port") or "8000"
        with self._lock:
            self._proc = subprocess.Popen(
                [docker, "logs", "-f", "--tail", "50", container_name],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
            self._model = model
            self._endpoint = parse_local_vllm_endpoint(endpoint or f"http://localhost:{port}")
            self._started_at = time.time()
            self._launcher = "docker"
            self._container_name = container_name
            self._reasoning_parser = _reasoning_parser_from_args(args)
            self._log_tail = [f"adopted running container {container_name}"]
            threading.Thread(target=self._drain_stdout, daemon=True).start()
        return True

    def detach(self) -> None:
        """API shutdown: a docker server keeps running; a binary child is stopped."""
        with self._lock:
            if self._launcher == "docker":
                if self._proc is not None and self._proc.poll() is None:
                    self._proc.terminate()
                self._proc = None
                return
            self._stop_locked()

    def _launch(
        self,
        command: list[str],
        env: dict[str, str],
        model: str,
        endpoint: VllmEndpoint,
        launcher: str,
        args: Sequence[str],
        *,
        container_name: str | None = None,
    ) -> None:
        self._proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        self._model = model
        self._endpoint = endpoint
        self._started_at = time.time()
        self._launcher = launcher
        self._container_name = container_name
        self._reasoning_parser = _reasoning_parser_from_args(args)
        self._log_tail = [" ".join(command), f"loading model={model}"]
        threading.Thread(target=self._drain_stdout, daemon=True).start()

    def stop(self) -> dict:
        with self._lock:
            self._stop_locked()
            return self.status()

    def status(self) -> dict:
        with self._lock:
            base = {
                "model": self._model,
                "endpoint": self._endpoint.api_url if self._endpoint else None,
                "launcher": self._launcher,
                "container_name": self._container_name,
                "reasoning_parser": self._reasoning_parser,
                "log_tail": list(self._log_tail[-MAX_LOG_LINES:]),
            }
            if self._launcher == "docker" and self._container_name:
                up = _container_running(self._container_name)
                return {
                    **base,
                    "state": "starting" if up else ("stopped" if self._proc is None else "failed"),
                    "pid": self._proc.pid if self._proc else None,
                    "uptime_seconds": (
                        round(time.time() - self._started_at, 1)
                        if up and self._started_at is not None else None
                    ),
                    "exit_code": None if up else 1,
                }
            if self._proc is None:
                return {
                    **base, "state": "stopped", "pid": None,
                    "uptime_seconds": None, "exit_code": None,
                }

            exit_code = self._proc.poll()
            running = exit_code is None
            state = "starting" if running else ("failed" if exit_code else "stopped")
            uptime = (
                round(time.time() - self._started_at, 1)
                if running and self._started_at is not None
                else None
            )
            return {
                **base,
                "state": state,
                "pid": self._proc.pid,
                "uptime_seconds": uptime,
                "exit_code": exit_code,
            }

    def _stop_locked(self) -> None:
        if self._launcher == "docker" and self._container_name and shutil.which("docker"):
            if _container_running(self._container_name):
                subprocess.run(
                    ["docker", "stop", "-t", "20", self._container_name],
                    capture_output=True, check=False,
                )
        if self._proc is None:
            return
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=25)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        self._proc = None
        self._started_at = None
        self._log_tail.append("managed vLLM stopped")

    def _drain_stdout(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            clean = line.strip()
            if not clean:
                continue
            with self._lock:
                self._log_tail.append(clean)
                if len(self._log_tail) > MAX_LOG_LINES:
                    del self._log_tail[: len(self._log_tail) - MAX_LOG_LINES]


def _container_running(name: str | None) -> bool:
    docker = shutil.which("docker")
    if not docker or not name:
        return False
    probe = subprocess.run(
        [docker, "inspect", "--format", "{{.State.Running}}", name],
        capture_output=True, text=True, check=False,
    )
    return probe.returncode == 0 and probe.stdout.strip() == "true"


def _arg_after(args: Sequence[str], flag: str) -> str | None:
    args = list(args)
    for i, arg in enumerate(args):
        if arg == flag and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith(flag + "="):
            return arg.split("=", 1)[1]
    return None


def _reasoning_parser_from_args(args: Sequence[str]) -> str | None:
    args = list(args)
    for i, arg in enumerate(args):
        if arg == "--reasoning-parser" and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith("--reasoning-parser="):
            return arg.split("=", 1)[1]
    return None


def parse_local_vllm_endpoint(endpoint: str | None = None) -> VllmEndpoint:
    raw = (endpoint or "http://localhost:8000").strip().rstrip("/")
    if raw.endswith("/v1"):
        raw = raw[:-3]
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("vLLM endpoint must be an http(s) URL")
    if parsed.hostname not in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        raise ValueError("managed vLLM can only start local endpoints")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    base_url = f"{parsed.scheme}://{parsed.hostname}:{port}"
    return VllmEndpoint(base_url=base_url, api_url=f"{base_url}/v1", port=port)
