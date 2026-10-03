"""Vehicle-count pack: one count per track, direction and class, SQLite totals, multi-pack."""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

import api.main as main_mod
from analytics.flow import FlowWindow
from api.main import app
from events.schemas import EventType
from packs.base import ReportWindow
from packs.runner import PackRunner
from packs.tracking import CentroidTracker
from packs.vehicle_count import VehicleCountConfig, VehicleCountPack
from vision.schemas import BoundingBox, InferenceFrame, VehicleClass, VehicleDetection

client = TestClient(app)

LINE = [[0.5, 0.1], [0.5, 0.9]]  # vertical line at x = 0.5, A at the top


def det(
    x: float, y: float, cls: VehicleClass = VehicleClass.car, track_id: str = "raw"
) -> VehicleDetection:
    return VehicleDetection(
        track_id=track_id, vehicle_class=cls,
        bounding_box=BoundingBox(x=x, y=y, width=0.08, height=0.06, confidence=0.9),
        frame_id="f", timestamp_ms=0,
    )


def window(ts: float) -> ReportWindow:
    return ReportWindow(camera_id="cam", report_interval_seconds=2, now_ts=ts)


def _drive(positions: list[list[tuple[float, float, VehicleClass]]], cfg: VehicleCountConfig):
    pack, tracker, flow = VehicleCountPack(), CentroidTracker(), FlowWindow(camera_id="cam")
    events = []
    ts = 100.0
    for frame in positions:
        tracked = tracker.update([det(x, y, c) for x, y, c in frame], ts)
        events += list(pack.evaluate(tracked, flow, cfg, window(ts)))
        for lost in tracker.lost:
            events += list(pack.on_track_lost(lost.track_id, cfg, window(ts)))
        ts += 1.0
    return events


def test_counts_once_with_direction_and_class() -> None:
    cfg = VehicleCountConfig(count_line=LINE, label_a_to_b="eastbound", label_b_to_a="westbound")
    # A car moving left→right crosses x=0.5 once and keeps going; a truck goes right→left.
    frames = [
        [(0.20, 0.5, VehicleClass.car), (0.80, 0.6, VehicleClass.truck)],
        [(0.35, 0.5, VehicleClass.car), (0.65, 0.6, VehicleClass.truck)],
        [(0.55, 0.5, VehicleClass.car), (0.40, 0.6, VehicleClass.truck)],
        [(0.70, 0.5, VehicleClass.car), (0.25, 0.6, VehicleClass.truck)],
        [(0.85, 0.5, VehicleClass.car), (0.10, 0.6, VehicleClass.truck)],
    ]
    events = _drive(frames, cfg)
    assert len(events) == 2
    by_type = {e.vehicle_type.value: e for e in events}
    assert set(by_type) == {"car", "truck"}
    assert by_type["car"].crossing != by_type["truck"].crossing
    assert {e.direction_label for e in events} == {"eastbound", "westbound"}
    assert all(e.event_type == EventType.vehicle_count for e in events)
    assert all(e.operator_review_recommended is False for e in events)
    assert by_type["car"].direction.compass == "E"
    assert by_type["truck"].direction.compass == "W"


def test_jitter_across_the_line_counts_once() -> None:
    cfg = VehicleCountConfig(count_line=LINE)
    # The same car sits on the line and jitters back and forth over it.
    xs = [0.40, 0.52, 0.48, 0.53, 0.47, 0.55, 0.60]
    events = _drive([[(x, 0.5, VehicleClass.car)] for x in xs], cfg)
    assert len(events) == 1


def test_pedestrians_and_outside_segment_not_counted() -> None:
    cfg = VehicleCountConfig(count_line=[[0.5, 0.4], [0.5, 0.6]])  # short segment
    people = [[(0.4, 0.5, VehicleClass.pedestrian)], [(0.6, 0.5, VehicleClass.pedestrian)]]
    events = _drive(people, cfg)
    assert events == []
    # A car crossing x=0.5 at y=0.9 is outside the drawn segment's extent.
    events = _drive([[(0.4, 0.9, VehicleClass.car)], [(0.6, 0.9, VehicleClass.car)]], cfg)
    assert events == []


def test_lost_track_can_be_recounted_only_after_loss() -> None:
    cfg = VehicleCountConfig(count_line=LINE)
    pack, flow = VehicleCountPack(), FlowWindow(camera_id="cam")
    a = det(0.4, 0.5, track_id="t1")
    a.metadata["track"] = {"observations": 3}
    b = det(0.6, 0.5, track_id="t1")
    b.metadata["track"] = {"observations": 4}
    assert list(pack.evaluate([a], flow, cfg, window(1))) == []
    assert len(list(pack.evaluate([b], flow, cfg, window(2)))) == 1
    # Back across and forward again without loss: still no second count.
    assert list(pack.evaluate([a], flow, cfg, window(3))) == []
    assert list(pack.evaluate([b], flow, cfg, window(4))) == []
    list(pack.on_track_lost("t1", cfg, window(5)))
    assert list(pack.evaluate([a], flow, cfg, window(6))) == []
    assert len(list(pack.evaluate([b], flow, cfg, window(7)))) == 1


def test_runner_runs_three_packs_on_one_camera_and_counts_persist() -> None:
    runner = PackRunner("cam-multi")
    runner.configure(
        bindings=[
            {
                "pack_id": "vehicle_count",
                "parameters": {"count_line": LINE, "min_observations": 1,
                               "label_a_to_b": "nb", "label_b_to_a": "sb"},
                "report_interval_seconds": 2,
            },
            {"pack_id": "moving_object", "parameters": {"min_observations": 1},
             "report_interval_seconds": 2},
            {"pack_id": "stop_sign", "parameters": {}, "report_interval_seconds": 2},
        ],
        stop_zone={"polygon": [[0.6, 0.4], [0.9, 0.4], [0.9, 0.7], [0.6, 0.7]],
                   "approach_direction": "N", "compliance_thresholds": {}},
        calibration=None,
    )
    assert set(runner.active_packs) == {"vehicle_count", "moving_object", "stop_sign"}
    ts = int(time.time() * 1000)
    frames = [
        [det(0.30, 0.5, VehicleClass.car), det(0.2, 0.2, VehicleClass.pedestrian)],
        [det(0.55, 0.5, VehicleClass.car), det(0.2, 0.2, VehicleClass.pedestrian)],
        [det(0.75, 0.5, VehicleClass.car)],
    ]
    emitted = []
    for i, dets in enumerate(frames):
        frame = InferenceFrame(frame_id=f"f{i}", camera_id="cam-multi", timestamp_ms=ts + i,
                               width=640, height=360, detections=dets)
        emitted += runner.process(frame)
    packs_seen = {pid for pid, _ in emitted}
    assert {"vehicle_count", "moving_object"} <= packs_seen
    counts = [e for pid, e in emitted if pid == "vehicle_count"]
    assert len(counts) == 1 and counts[0].direction_label == "nb"
    # Persist through the SQLite store and read the summary back.
    for pid, event in emitted:
        main_mod._store.add_event(event, pack_id=pid)
    summary = client.get("/cameras/cam-multi/counts").json()
    assert summary["total"] >= 1 and summary["by_type"].get("car", 0) >= 1
    assert summary["by_direction"].get("nb", 0) >= 1
    assert summary["hourly"] and summary["hourly"][-1]["total"] >= 1
    # Count records never enter the review queue.
    queue = client.get("/events/review-queue?status=pending").json()["events"]
    assert all(e["event_type"] != "vehicle_count" for e in queue)


def test_bindings_api_accepts_four_packs_and_requires_count_line() -> None:
    cam = client.post("/cameras", json={"name": "Four pack cam", "profile": "synthetic"}).json()
    cid = cam["id"]
    try:
        missing = client.put(f"/cameras/{cid}/bindings", json={"bindings": [
            {"pack_id": "vehicle_count", "parameters": {}, "report_interval_seconds": 2}]})
        assert missing.status_code == 422
        assert missing.json()["detail"]["prerequisite"] == "count_line"
        zone = {"polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]}
        client.put(f"/cameras/{cid}/stop-zone", json=zone)
        ok = client.put(f"/cameras/{cid}/bindings", json={"bindings": [
            {"pack_id": "vehicle_count", "parameters": {"count_line": LINE},
             "report_interval_seconds": 2},
            {"pack_id": "moving_object", "parameters": {}, "report_interval_seconds": 2},
            {"pack_id": "stop_sign", "parameters": {}, "report_interval_seconds": 2},
        ]})
        assert ok.status_code == 200, ok.text
        assert len(client.get(f"/cameras/{cid}/bindings").json()) == 3
        bad = client.put(f"/cameras/{cid}/bindings", json={"bindings": [
            {"pack_id": "vehicle_count", "parameters": {"count_line": LINE},
             "report_interval_seconds": 2},
            {"pack_id": "speed_violation", "parameters": {}, "report_interval_seconds": 2},
            {"pack_id": "stop_sign", "parameters": {}, "report_interval_seconds": 2},
        ]})
        assert bad.status_code == 422
        assert bad.json()["detail"]["error"] == "incompatible_pack_selection"
    finally:
        client.delete(f"/cameras/{cid}")


def test_review_ground_truth_round_trip() -> None:
    from datetime import UTC, datetime

    from events.schemas import Severity, StopSignEvent

    now = datetime.now(UTC)
    ev = StopSignEvent(
        event_id="gt-1", camera_id="cam-gt", event_type=EventType.stop_sign_violation,
        severity=Severity.warning, timestamp=now, decision="rolling_stop", min_speed_in_zone=0.05,
        dwell_ms=300, vehicle_type="car", vehicle_color="unknown", vehicle_descriptor="car",
        direction={}, track_id="t9", detected_at=now, operator_review_recommended=True,
    )
    main_mod._store.add_event(ev, pack_id="stop_sign")
    r = client.post(
        "/events/gt-1/review",
        json={"status": "confirmed", "note": "seen", "ground_truth": "my car, full stop"},
    )
    assert r.status_code == 200 and r.json()["ground_truth"] == "my car, full stop"
    assert client.get("/events/gt-1").json()["ground_truth"] == "my car, full stop"
    listed = client.get("/events/ground-truth?camera_id=cam-gt").json()
    assert [e["event_id"] for e in listed] == ["gt-1"]
    # A later review without ground_truth keeps the note.
    r = client.post("/events/gt-1/review", json={"status": "dismissed"})
    assert r.json()["ground_truth"] == "my car, full stop"
