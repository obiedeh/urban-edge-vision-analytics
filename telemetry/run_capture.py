"""Capture a measured live-camera run from a running Urban Edge API.

Run on the device next to the API (``python -m telemetry.run_capture``). For
``--duration`` seconds it subscribes to ``/live/results`` for one camera,
polls ``/runtime/status``, samples ``tegrastats`` at 1 Hz when present, and
writes ``artifacts/runs/<name>/run.json`` plus a tegrastats sidecar.

Every number in the artifact comes from the API or tegrastats; nothing is
typed by hand. Camera credentials never appear: the artifact records the
camera's profile, quality and masked URL only.

The script never starts or stops a model server. It refuses to start unless
the model server is healthy, aborts (writing a partial artifact marked
failed) if the server stays down for ``--outage-abort`` seconds mid-run, and
records every model-server event the API logged during the run. To make the
measurement attributable, ``--pause-other-app URL`` disables the other
app's enabled cameras for the duration and re-enables them afterwards.
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

SCHEMA = "urban-edge-live-run-v1"

_RAIL_RE = re.compile(r"(V[A-Z0-9_]+)\s+(\d+)mW/(\d+)mW")
_TEMP_RE = re.compile(r"([a-z0-9]+)@([0-9.]+)C")
_RAM_RE = re.compile(r"RAM (\d+)/(\d+)MB")


_EVIDENCE_NOTES = {
    "uploaded_recorded": "uploaded recording, not a live camera",
    "uploaded_generated": "generated footage, not a live camera",
    "synthetic": "synthetic test feed, not a live camera",
}


def _evidence_note(source_kind: Any) -> str | None:
    """Label for non-live sources; ``None`` for live cameras."""
    return _EVIDENCE_NOTES.get(str(source_kind)) if source_kind else None


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1)))
    return round(ordered[idx], 3)


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
        "p99": _percentile(values, 99),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "mean": round(sum(values) / len(values), 3),
    }


class Tegrastats:
    def __init__(self) -> None:
        self.samples: list[dict[str, Any]] = []
        self._proc: subprocess.Popen[str] | None = None

    def start(self) -> bool:
        try:
            self._proc = subprocess.Popen(
                ["tegrastats", "--interval", "1000"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            )
        except OSError:
            return False
        threading.Thread(target=self._pump, daemon=True).start()
        return True

    def _pump(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            sample: dict[str, Any] = {"t": time.time()}
            ram = _RAM_RE.search(line)
            if ram:
                sample["ram_used_mb"] = int(ram.group(1))
                sample["ram_total_mb"] = int(ram.group(2))
            sample["temps_c"] = {k: float(v) for k, v in _TEMP_RE.findall(line)}
            sample["rails_mw"] = {k: int(v) for k, v, _ in _RAIL_RE.findall(line)}
            self.samples.append(sample)

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def summary(self) -> dict[str, Any] | None:
        if not self.samples:
            return None
        rails: dict[str, list[float]] = {}
        temps: dict[str, list[float]] = {}
        ram: list[float] = []
        for s in self.samples:
            for k, v in s.get("rails_mw", {}).items():
                rails.setdefault(k, []).append(float(v))
            for k, v in s.get("temps_c", {}).items():
                temps.setdefault(k, []).append(float(v))
            if "ram_used_mb" in s:
                ram.append(float(s["ram_used_mb"]))
        return {
            "n_samples": len(self.samples),
            "rails_mw": {
                k: {"p50": _percentile(v, 50), "peak": max(v), "min": min(v)}
                for k, v in rails.items()
            },
            "temps_c": {
                k: {"p50": _percentile(v, 50), "peak": max(v)} for k, v in temps.items()
            },
            "board_ram_used_mb": (
                {"p50": _percentile(ram, 50), "peak": max(ram)} if ram else None
            ),
        }


def _device() -> dict[str, Any]:
    def read(path: str) -> str | None:
        try:
            return Path(path).read_text(errors="replace").strip("\x00\n ")
        except OSError:
            return None

    def run(cmd: list[str]) -> str | None:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
            return out.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            return None

    l4t = read("/etc/nv_tegra_release")
    return {
        "host": platform.node(),
        "machine": platform.machine(),
        "kernel": platform.release(),
        "model": read("/proc/device-tree/model"),
        "l4t_release": l4t.splitlines()[0] if l4t else None,
        "nvpmodel": (run(["nvpmodel", "-q"]) or "").replace("\n", " ") or None,
        "python": platform.python_version(),
        "git_sha": run(["git", "rev-parse", "--short", "HEAD"]),
        "git_dirty": bool(run(["git", "status", "--porcelain"])),
    }


class ModelServerNotReady(SystemExit):
    pass


def preflight(client: httpx.Client, camera_id: str) -> dict[str, Any]:
    """Refuse to record unless the camera streams and the model server answers."""
    status = client.get("/runtime/status").json()
    cam = next((c for c in status["cameras"] if c["camera_id"] == camera_id), None)
    if cam is None:
        raise ModelServerNotReady(f"camera {camera_id} is not running on this API")
    if cam["state"] != "streaming":
        raise ModelServerNotReady(f"camera {camera_id} is {cam['state']}, not streaming")
    model = status["model"]
    if model["backend"] == "mock":
        raise ModelServerNotReady("model backend is mock; a live run needs a real model")
    endpoint = model["endpoint"].rstrip("/")
    try:
        served = httpx.get(f"{endpoint}/models", timeout=5).json().get("data", [])
    except Exception as exc:
        raise ModelServerNotReady(f"model server at {endpoint} is not answering: {exc}") from exc
    ids = [m.get("id") for m in served]
    if model["model"] not in ids:
        raise ModelServerNotReady(f"model server serves {ids}, not {model['model']}")
    if model["state"] == "unavailable":
        raise ModelServerNotReady(f"model runtime reports unavailable: {model.get('last_error')}")
    return status


class OtherApp:
    """Disable the other app's cameras for the run so inference load is attributable."""

    def __init__(self, base_url: str | None) -> None:
        self.base = base_url.rstrip("/") if base_url else None
        self.paused: list[tuple[str, str]] = []  # (kind, camera_id)

    def pause(self) -> list[str]:
        if not self.base:
            return []
        client = httpx.Client(base_url=self.base, timeout=20)
        # Safety Observability (/config/cameras) or another Urban Edge (/cameras).
        for kind, path in (("safety", "/config/cameras"), ("urban-edge", "/cameras")):
            try:
                cams = client.get(path).json()
            except Exception:
                continue
            if not isinstance(cams, list):
                continue
            for cam in cams:
                cid = cam.get("camera_id") or cam.get("id")
                if cam.get("enabled") and cid:
                    client.post(f"{path}/{cid}/enabled", json={"enabled": False})
                    self.paused.append((kind, cid))
            break
        return [cid for _, cid in self.paused]

    def resume(self) -> None:
        if not self.base or not self.paused:
            return
        client = httpx.Client(base_url=self.base, timeout=20)
        for kind, cid in self.paused:
            path = "/config/cameras" if kind == "safety" else "/cameras"
            try:
                client.post(f"{path}/{cid}/enabled", json={"enabled": True})
            except Exception as exc:
                print(f"warning: could not re-enable {cid} on {self.base}: {exc}", file=sys.stderr)


def capture(
    api: str,
    camera_id: str,
    duration_s: float,
    out_dir: Path,
    name: str,
    notes: str,
    *,
    other_app: str | None = None,
    outage_abort_s: float = 60.0,
) -> Path:
    client = httpx.Client(base_url=api, timeout=30)
    status0 = preflight(client, camera_id)
    other = OtherApp(other_app)
    paused = other.pause()
    run_notes: list[str] = []
    if paused:
        run_notes.append(f"paused {len(paused)} camera(s) on {other_app} for the run: {paused}")
    model_endpoint = status0["model"]["endpoint"].rstrip("/")
    aborted: str | None = None
    cam0 = next((c for c in status0["cameras"] if c["camera_id"] == camera_id), None)
    if cam0 is None:
        sys.exit(f"camera {camera_id} is not running on {api}")
    camera = client.get(f"/cameras/{camera_id}").json()
    bindings = client.get(f"/cameras/{camera_id}/bindings").json()
    events_before = client.get("/runtime").json().get("event_count", 0)

    tegra = Tegrastats()
    tegra_ok = tegra.start()
    results: list[dict[str, Any]] = []
    status_samples: list[dict[str, Any]] = []
    stop = threading.Event()

    def sse() -> None:
        url = f"{api}/live/results"
        with httpx.stream("GET", url, params={"camera_id": camera_id}, timeout=None) as r:
            for line in r.iter_lines():
                if stop.is_set():
                    return
                if line.startswith("data:") and '"camera_id"' in line:
                    try:
                        results.append(json.loads(line[5:].strip()))
                    except json.JSONDecodeError:
                        continue

    t = threading.Thread(target=sse, daemon=True)
    started = time.time()
    started_iso = datetime.now(UTC).isoformat()
    t.start()
    outage_since: float | None = None
    while time.time() - started < duration_s:
        time.sleep(2.0)
        try:
            st = client.get("/runtime/status").json()
            model_down = st["model"]["state"] == "unavailable"
            if not model_down:
                try:
                    httpx.get(f"{model_endpoint}/models", timeout=3).raise_for_status()
                except Exception:
                    model_down = True
            if model_down:
                if outage_since is None:
                    outage_since = time.time()
                    run_notes.append(
                        f"model server outage detected at {datetime.now(UTC).isoformat()}"
                    )
                elif time.time() - outage_since > outage_abort_s:
                    aborted = (
                        f"model server down for {int(time.time() - outage_since)} s; run aborted"
                    )
                    run_notes.append(aborted)
                    print(f"ABORT: {aborted}", file=sys.stderr)
                    break
            elif outage_since is not None:
                run_notes.append(
                    f"model server recovered after {int(time.time() - outage_since)} s"
                )
                outage_since = None
            cam = next((c for c in st["cameras"] if c["camera_id"] == camera_id), None)
            if cam:
                status_samples.append(
                    {
                        "t": time.time(),
                        "fps": cam["fps"],
                        "frames_published": cam["frames_published"],
                        "frames_dropped": cam["frames_dropped"],
                        "reconnects": cam["reconnects"],
                        "state": cam["state"],
                        "model_state": st["model"]["state"],
                    }
                )
        except httpx.HTTPError:
            pass
    stop.set()
    elapsed = time.time() - started
    tegra.stop()
    other.resume()
    if paused:
        run_notes.append(f"re-enabled {len(paused)} camera(s) on {other_app}")
    status1 = client.get("/runtime/status").json()
    cam1 = next((c for c in status1["cameras"] if c["camera_id"] == camera_id), cam0)
    events_after = client.get("/runtime").json().get("event_count", 0)
    run_events = client.get("/events", params={"camera_id": camera_id, "limit": 500}).json()
    run_events = [e for e in run_events if e.get("timestamp", "") >= started_iso]

    # Drop the replayed pre-run result (first SSE message is the last known state).
    ok_results = [
        r for r in results
        if r.get("metadata", {}).get("status") == "ok"
        and r.get("timestamp_ms", 0) / 1000 >= started
    ]
    latencies = [
        float(r["inference_latency_ms"]) for r in ok_results
        if r.get("inference_latency_ms") is not None
    ]
    statuses: dict[str, int] = {}
    for r in results:
        s = r.get("metadata", {}).get("status", "unknown")
        statuses[s] = statuses.get(s, 0) + 1
    completion = [
        r["metadata"]["completion_tokens"] for r in ok_results
        if r["metadata"].get("completion_tokens") is not None
    ]
    prompt_tok = [
        r["metadata"]["prompt_tokens"] for r in ok_results
        if r["metadata"].get("prompt_tokens") is not None
    ]
    model_keys = ("backend", "model", "endpoint", "label", "think", "state", "total_calls",
                  "total_failures")
    published = cam1["frames_published"] - cam0["frames_published"]

    server_events = [
        e for e in status1.get("server_events", []) if e.get("at", "") >= started_iso
    ]
    report = {
        "schema": SCHEMA,
        "name": name,
        "status": "failed" if aborted else "complete",
        "error": aborted,
        "notes": notes,
        "run_notes": run_notes,
        "model_server_events": server_events,
        "started_at": started_iso,
        "finished_at": datetime.now(UTC).isoformat(),
        "duration_s": round(elapsed, 2),
        "device": _device(),
        "api": {"version": client.get("/health").json().get("version"), "host": status1["host"]},
        "model": {k: status1["model"][k] for k in model_keys},
        "inference_settings": status1["inference"],
        # Where the frames came from. Evidence from uploads or the synthetic feed
        # is labelled so a run on recorded footage is never read as a live run.
        "source_kind": camera.get("source_kind"),
        "evidence_note": _evidence_note(camera.get("source_kind")),
        "camera": {
            "camera_id": camera_id,
            "name": camera.get("name"),
            "profile": camera.get("profile"),
            "source_kind": camera.get("source_kind"),
            "stream_quality": camera.get("stream_quality"),
            "effective_stream_path": camera.get("effective_stream_path"),
            "rtsp_transport": camera.get("rtsp_transport"),
            "masked_url": camera.get("masked_url"),
            "codec": cam1.get("codec"),
            "source_resolution": [cam1.get("source_width"), cam1.get("source_height")],
            "source_fps": cam1.get("source_fps"),
            "packs": [b.get("pack_id") for b in bindings],
        },
        "video": {
            "frames_published_in_run": cam1["frames_published"] - cam0["frames_published"],
            "frames_decoded_in_run": cam1["frames_decoded"] - cam0["frames_decoded"],
            "frames_dropped_in_run": cam1["frames_dropped"] - cam0["frames_dropped"],
            "reconnects_in_run": cam1["reconnects"] - cam0["reconnects"],
            "display_fps_mean": round(published / elapsed, 3),
            "display_fps_samples": _stats([s["fps"] for s in status_samples]),
            "camera_states_seen": sorted({s["state"] for s in status_samples}),
        },
        "inference": {
            "results_received": len(results),
            "results_ok": len(ok_results),
            "status_counts": statuses,
            "inference_latency_ms": _stats(latencies),
            "results_per_second": round(len(ok_results) / elapsed, 3) if elapsed else None,
            "detections_per_result": _stats([float(r.get("vehicle_count", 0)) for r in ok_results]),
            "completion_tokens": _stats([float(v) for v in completion]),
            "prompt_tokens": _stats([float(v) for v in prompt_tok]),
            "model_calls_in_run": (
                status1["model"]["total_calls"] - status0["model"]["total_calls"]
            ),
            "model_failures_in_run": (
                status1["model"]["total_failures"] - status0["model"]["total_failures"]
            ),
        },
        "events": {
            "produced_in_run": max(0, events_after - events_before),
            "by_type": _count(run_events, "event_type"),
            "by_pack": _count(run_events, "pack_id"),
            "review_recommended": sum(
                1 for e in run_events if e.get("operator_review_recommended")
            ),
        },
        "ground_truth": _ground_truth_section(client, camera_id, started_iso, report_until=None),
        "tegrastats": tegra.summary() if tegra_ok else None,
        "samples": {
            "status": status_samples,
            "results": [
                {
                    "t": r.get("timestamp_ms"),
                    "status": r.get("metadata", {}).get("status"),
                    "latency_ms": r.get("inference_latency_ms"),
                    "detections": r.get("vehicle_count"),
                    "summary": (r.get("vlm_summary") or "")[:200],
                }
                for r in results
            ],
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "run.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    if tegra.samples:
        with (out_dir / "tegrastats.jsonl").open("w") as fh:
            for s in tegra.samples:
                fh.write(json.dumps(s) + "\n")
    return path


def _ground_truth_section(
    client: httpx.Client, camera_id: str, since: str, report_until: str | None
) -> dict[str, Any]:
    """Pack output against the operator's known passes (Review → ground truth)."""
    params: dict[str, str] = {"camera_id": camera_id, "since": since}
    if report_until:
        params["until"] = report_until
    try:
        annotated = client.get("/events/ground-truth", params=params).json()
    except httpx.HTTPError:
        annotated = []
    rows = []
    for e in annotated:
        rows.append(
            {
                "event_id": e.get("event_id"),
                "timestamp": e.get("timestamp"),
                "pack_id": e.get("pack_id"),
                "event_type": e.get("event_type"),
                "ground_truth": e.get("ground_truth"),
                "review_status": e.get("review_status"),
                "pack_output": {
                    k: e.get(k)
                    for k in (
                        "decision", "dwell_ms", "min_speed_in_zone", "measured_speed", "unit",
                        "posted_speed", "exceedance", "vehicle_type", "direction_label",
                        "crossing", "person_descriptor", "confidence",
                    )
                    if e.get(k) is not None
                },
            }
        )
    return {
        "note": (
            "Operator-entered descriptions of known passes, recorded in Review after the run. "
            "Pack output is listed beside each; no automatic match or accuracy figure is computed."
        ),
        "annotated_events": rows,
        "count": len(rows),
    }


def annotate(api: str, path: Path) -> Path:
    """Refresh the ground_truth section of an existing artifact from Review annotations."""
    report = json.loads(path.read_text())
    client = httpx.Client(base_url=api, timeout=30)
    report["ground_truth"] = _ground_truth_section(
        client, report["camera"]["camera_id"], report["started_at"], report.get("finished_at")
    )
    report["ground_truth"]["annotated_at"] = datetime.now(UTC).isoformat()
    path.write_text(json.dumps(report, indent=2) + "\n")
    return path


def _count(events: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in events:
        k = str(e.get(key) or "none")
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture a measured live run from the Urban Edge API."
    )
    parser.add_argument("--api", default="http://127.0.0.1:8080")
    parser.add_argument(
        "--annotate",
        metavar="RUN_JSON",
        help="Refresh the ground_truth section of an existing artifact from Review and exit",
    )
    parser.add_argument("--camera-id")
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--name", help="artifact name, e.g. thor-tapo-cosmos2b")
    parser.add_argument("--notes", default="")
    parser.add_argument("--out", default="artifacts/runs")
    parser.add_argument(
        "--pause-other-app", metavar="URL",
        help="Disable the other app's enabled cameras for the run (e.g. http://127.0.0.1:8081)",
    )
    parser.add_argument(
        "--outage-abort", type=float, default=60.0,
        help="Abort if the model server stays down this many seconds mid-run",
    )
    args = parser.parse_args()
    if args.annotate:
        out = annotate(args.api, Path(args.annotate))
        gt = json.loads(out.read_text())["ground_truth"]
        print(f"updated {out}: {gt['count']} annotated events")
        return
    if not args.camera_id or not args.name:
        parser.error("--camera-id and --name are required to capture a run")
    path = capture(
        args.api, args.camera_id, args.duration, Path(args.out) / args.name, args.name, args.notes,
        other_app=args.pause_other_app, outage_abort_s=args.outage_abort,
    )
    data = json.loads(path.read_text())
    print(f"written {path} ({data['status']})")
    for note in data["run_notes"]:
        print(f"note: {note}")
    video, inf = data["video"], data["inference"]
    print(f"video: {video['display_fps_mean']} fps mean, dropped {video['frames_dropped_in_run']}")
    lat = inf["inference_latency_ms"]
    print(
        f"inference: {inf['results_ok']} ok results, "
        f"p50 {lat.get('p50')} ms, p95 {lat.get('p95')} ms"
    )
    print(f"events: {data['events']['produced_in_run']}")
    if data["tegrastats"]:
        vin = data["tegrastats"]["rails_mw"].get("VIN") or {}
        print(f"power VIN p50 {vin.get('p50')} mW peak {vin.get('peak')} mW")


if __name__ == "__main__":
    main()
