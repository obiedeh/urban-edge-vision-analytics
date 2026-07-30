from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import urlparse

MAX_LOG_LINES = 1000


@dataclass(frozen=True)
class VllmEndpoint:
    base_url: str
    api_url: str
    port: int


class VllmServerManager:
    """Owns a single local vLLM server process started by this API."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None
        self._model: str | None = None
        self._endpoint: VllmEndpoint | None = None
        self._started_at: float | None = None
        self._log_tail: list[str] = []
        self._lock = threading.RLock()

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
                if (
                    self._model == selected_model
                    and self._endpoint == selected_endpoint
                ):
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

            command = [
                vllm_bin,
                "serve",
                selected_model,
                "--host",
                "0.0.0.0",
                "--port",
                str(selected_endpoint.port),
                *(extra_args or []),
            ]
            env = {
                **os.environ,
                "PYTHONUNBUFFERED": "1",
                **{k: str(v) for k, v in (extra_env or {}).items()},
            }
            self._proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
            self._model = selected_model
            self._endpoint = selected_endpoint
            self._started_at = time.time()
            self._log_tail = [
                " ".join(command),
                f"loading model={selected_model}",
            ]
            threading.Thread(target=self._drain_stdout, daemon=True).start()
            return self.status()

    def stop(self) -> dict:
        with self._lock:
            self._stop_locked()
            return self.status()

    def status(self) -> dict:
        with self._lock:
            if self._proc is None:
                return {
                    "state": "stopped",
                    "pid": None,
                    "model": self._model,
                    "endpoint": self._endpoint.api_url if self._endpoint else None,
                    "uptime_seconds": None,
                    "exit_code": None,
                    "log_tail": list(self._log_tail[-MAX_LOG_LINES:]),
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
                "state": state,
                "pid": self._proc.pid,
                "model": self._model,
                "endpoint": self._endpoint.api_url if self._endpoint else None,
                "uptime_seconds": uptime,
                "exit_code": exit_code,
                "log_tail": list(self._log_tail[-MAX_LOG_LINES:]),
            }

    def _stop_locked(self) -> None:
        if self._proc is None:
            return
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=15)
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
