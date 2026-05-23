from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path
from threading import Lock


class PipelineManager:
    """Manages a single vision inference pipeline subprocess.

    The pipeline reads from a camera config file and POSTs events to the local API.
    When the mock adapter is active (or ffmpeg is absent) it uses synthetic frames so
    the full event pipeline works without a physical camera.
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._started_at: float | None = None
        self._camera_id: str | None = None
        self._adapter: str = "mock"
        self._synthetic: bool = False
        self._config_path: str | None = None
        self._lock = Lock()
        self._last_lines: list[str] = []   # rolling tail of stdout

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(
        self,
        config_path: str | Path,
        adapter: str = "mock",
        api_url: str = "http://127.0.0.1:8080",
        sample_fps: float = 1.0,
        nvidia_endpoint: str | None = None,
        nvidia_api_key: str | None = None,
        synthetic: bool = False,
        local_model: str | None = None,
        local_endpoint: str | None = None,
    ) -> None:
        """Kill any running pipeline and start a fresh one for the given config.

        If ``synthetic=True`` the pipeline generates fake frames instead of
        reading an RTSP stream — useful for demo cameras with no physical hardware.
        If ffmpeg is absent the pipeline always falls back to synthetic mode.
        """
        with self._lock:
            self._stop_locked()

            # Resolve adapter — fall back to "mock" for unknown names
            valid_adapters = {"mock", "ollama", "vllm", "nvidia-nim", "nvidia-vss", "nvidia-cosmos"}
            resolved_adapter = adapter if adapter in valid_adapters else "mock"

            # Use synthetic when explicitly requested OR when ffmpeg is absent
            use_synthetic = synthetic or shutil.which("ffmpeg") is None

            cmd = [
                sys.executable, "-m", "vision.live_pipeline",
                "--config", str(config_path),
                "--api-url", api_url,
                "--detector", resolved_adapter,
                "--sample-fps", str(sample_fps),
                "--frames", "0",
            ]
            if use_synthetic:
                cmd.append("--synthetic")
            if local_model:
                cmd += ["--detector-model", local_model]

            # Pass credentials / endpoints via environment
            extra_env = {}
            if nvidia_endpoint:
                extra_env["NVIDIA_VISION_ENDPOINT"] = nvidia_endpoint
            if nvidia_api_key:
                extra_env["NVIDIA_API_KEY"] = nvidia_api_key
            # Local adapters: pass selected model and endpoint via env
            if local_model and resolved_adapter == "ollama":
                extra_env["OLLAMA_MODEL"] = local_model
            if local_model and resolved_adapter == "vllm":
                extra_env["VLLM_MODEL"] = local_model
            if local_endpoint and resolved_adapter == "ollama":
                extra_env["OLLAMA_ENDPOINT"] = local_endpoint
            if local_endpoint and resolved_adapter == "vllm":
                extra_env["VLLM_ENDPOINT"] = local_endpoint

            import os as _os
            env = {**_os.environ, **extra_env}

            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
            self._started_at = time.time()
            self._config_path = str(config_path)
            self._adapter = resolved_adapter
            self._synthetic = use_synthetic
            self._last_lines = []

            # Drain stdout in a background thread so the pipe doesn't block
            import threading
            threading.Thread(target=self._drain_stdout, daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    @property
    def status(self) -> dict:
        with self._lock:
            if self._proc is None:
                return {
                    "state": "stopped",
                    "pid": None,
                    "uptime_seconds": None,
                    "camera_id": None,
                    "adapter": None,
                    "synthetic": None,
                    "log_tail": [],
                }
            rc = self._proc.poll()
            if rc is None:
                return {
                    "state": "running",
                    "pid": self._proc.pid,
                    "uptime_seconds": round(time.time() - (self._started_at or time.time()), 1),
                    "camera_id": self._camera_id,
                    "adapter": self._adapter,
                    "synthetic": self._synthetic,
                    "config_path": self._config_path,
                    "log_tail": list(self._last_lines[-10:]),
                }
            return {
                "state": "failed" if rc != 0 else "completed",
                "pid": self._proc.pid,
                "exit_code": rc,
                "uptime_seconds": None,
                "camera_id": self._camera_id,
                "adapter": self._adapter,
                "synthetic": self._synthetic,
                "log_tail": list(self._last_lines[-10:]),
            }

    # ── Internals ──────────────────────────────────────────────────────────────

    def _stop_locked(self) -> None:
        if self._proc is None:
            return
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        self._proc = None
        self._started_at = None

    def _drain_stdout(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                # Extract camera_id from startup line
                if line.startswith("camera_id=") and self._camera_id is None:
                    self._camera_id = line.split("=", 1)[1]
                with self._lock:
                    self._last_lines.append(line)
                    if len(self._last_lines) > 50:
                        self._last_lines.pop(0)
