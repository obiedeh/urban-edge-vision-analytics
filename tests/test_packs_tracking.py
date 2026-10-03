"""Tracker, geometry and the three use-case packs on tracked detections."""
from __future__ import annotations

import time

from analytics.flow import FlowWindow
from packs.base import PackId, ReportWindow
from packs.geometry import crossed_gate, point_in_polygon
from packs.moving_object import MovingObjectConfig, MovingObjectPack
from packs.runner import PackRunner
from packs.speed_violation import (
    SpeedCalibrationConfig,
    SpeedViolationConfig,
    SpeedViolationPack,
)
from packs.stop_sign import StopSignConfig, StopSignPack, StopZone
from packs.tracking import CentroidTracker
from vision.schemas import BoundingBox, InferenceFrame, VehicleClass, VehicleDetection


def det(x: float, y: float, cls: VehicleClass = VehicleClass.car, w: float = 0.1, h: float = 0.08,
        track_id: str = "raw", conf: float = 0.9) -> VehicleDetection:
    return VehicleDetection(
        track_id=track_id, vehicle_class=cls,
        bounding_box=BoundingBox(x=x, y=y, width=w, height=h, confidence=conf),
        frame_id="f", timestamp_ms=0,
    )


def window(ts: float, camera_id: str = "cam") -> ReportWindow:
    return ReportWindow(camera_id=camera_id, report_interval_seconds=2, now_ts=ts)


# ── geometry ──────────────────────────────────────────────────────────────────


def test_point_in_polygon() -> None:
    square = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]
    assert point_in_polygon((0.5, 0.5), square)
    assert not point_in_polygon((0.1, 0.5), square)


def test_crossed_gate_line_and_polygon() -> None:
    line = [[0.5, 0.0], [0.5, 1.0]]
    assert crossed_gate((0.4, 0.5), (0.6, 0.5), line)
    assert not crossed_gate((0.3, 0.5), (0.4, 0.5), line)
    assert not crossed_gate((0.4, 1.5), (0.6, 1.5), line)  # outside the segment extent
    poly = [[0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.6]]
    assert crossed_gate((0.1, 0.5), (0.5, 0.5), poly)


# ── tracker ───────────────────────────────────────────────────────────────────


def test_tracker_keeps_ids_across_frames_and_reports_velocity() -> None:
    tracker = CentroidTracker()
    t0 = 1000.0
    a = tracker.update([det(0.10, 0.5)], t0)
    b = tracker.update([det(0.15, 0.5)], t0 + 1.0)
    c = tracker.update([det(0.20, 0.5)], t0 + 2.0)
    assert a[0].track_id == b[0].track_id == c[0].track_id
    assert c[0].metadata["track"]["vx"] > 0.04
    assert c[0].metadata["track"]["observations"] == 3
    # A far-away new object gets a new id; the old one is lost after misses.
    d = tracker.update([det(0.9, 0.1)], t0 + 3.0)
    assert d[0].track_id != c[0].track_id
    for i in range(4):
        tracker.update([det(0.9, 0.1)], t0 + 4.0 + i)
    lost_ids = {t.track_id for t in tracker.lost}
    assert c[0].track_id in lost_ids or c[0].track_id not in tracker.tracks


def test_tracker_does_not_merge_people_with_vehicles() -> None:
    tracker = CentroidTracker()
    a = tracker.update([det(0.5, 0.5, VehicleClass.car)], 1.0)
    b = tracker.update([det(0.5, 0.5, VehicleClass.pedestrian)], 2.0)
    assert a[0].track_id != b[0].track_id


# ── stop sign ─────────────────────────────────────────────────────────────────

ZONE = StopZone(polygon=[[0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.6]])


def _run_stop_sequence(positions: list[tuple[float, float]], dt: float = 1.0):
    pack = StopSignPack()
    tracker = CentroidTracker()
    cfg = StopSignConfig(stop_zone=ZONE, dwell_threshold_ms=1500)
    flow = FlowWindow(camera_id="cam")
    events = []
    ts = 100.0
    for x, y in positions:
        tracked = tracker.update([det(x, y)], ts)
        events += list(pack.evaluate(tracked, flow, cfg, window(ts)))
        ts += dt
    return events


def test_stop_sign_compliant_when_vehicle_dwells() -> None:
    # Approach, sit still in the zone for 3 s, leave.
    events = _run_stop_sequence(
        [(0.1, 0.46), (0.3, 0.46), (0.45, 0.46), (0.45, 0.46), (0.45, 0.46), (0.45, 0.46),
         (0.7, 0.46), (0.9, 0.46)]
    )
    assert len(events) == 1
    assert events[0].decision == "compliant"
    assert events[0].dwell_ms >= 1500
    assert events[0].operator_review_recommended is False


def test_stop_sign_no_stop_when_vehicle_rolls_through() -> None:
    events = _run_stop_sequence([(0.1, 0.46), (0.3, 0.46), (0.45, 0.46), (0.65, 0.46), (0.9, 0.46)])
    assert len(events) == 1
    assert events[0].decision in {"no_stop", "rolling_stop"}
    assert events[0].operator_review_recommended is True
    assert events[0].metadata["speed_unit"] == "frame_widths_per_second"


def test_stop_sign_ignores_pedestrians_and_outside_zone() -> None:
    pack = StopSignPack()
    cfg = StopSignConfig(stop_zone=ZONE)
    flow = FlowWindow(camera_id="cam")
    person = [det(0.45, 0.46, VehicleClass.pedestrian)]
    assert list(pack.evaluate(person, flow, cfg, window(1))) == []
    assert list(pack.evaluate([det(0.1, 0.1)], flow, cfg, window(1))) == []


# ── speed ─────────────────────────────────────────────────────────────────────


def test_speed_violation_measured_between_gates() -> None:
    pack = SpeedViolationPack()
    tracker = CentroidTracker()
    cal = SpeedCalibrationConfig(
        gate_a=[[0.3, 0.0], [0.3, 1.0]], gate_b=[[0.7, 0.0], [0.7, 1.0]],
        real_world_distance_m=20.0, posted_speed_kph=30.0,
    )
    cfg = SpeedViolationConfig(calibration=cal)
    flow = FlowWindow(camera_id="cam")
    events = []
    ts = 50.0
    # Crosses A at ~t=51, B at ~t=53 → 20 m in 2 s = 36 kph > 30 posted.
    for x in (0.2, 0.35, 0.55, 0.75, 0.9):
        tracked = tracker.update([det(x, 0.5, w=0.05, h=0.05)], ts)
        events += list(pack.evaluate(tracked, flow, cfg, window(ts)))
        ts += 1.0
    assert len(events) == 1
    ev = events[0]
    assert 30 < ev.measured_speed < 40
    assert ev.exceedance > 0 and ev.operator_review_recommended
    assert ev.metadata["transit_s"] == 2.0


def test_speed_violation_requires_calibration_and_skips_slow_vehicles() -> None:
    pack = SpeedViolationPack()
    flow = FlowWindow(camera_id="cam")
    assert list(pack.evaluate([det(0.5, 0.5)], flow, SpeedViolationConfig(), window(1))) == []
    cal = SpeedCalibrationConfig(
        gate_a=[[0.3, 0.0], [0.3, 1.0]], gate_b=[[0.7, 0.0], [0.7, 1.0]],
        real_world_distance_m=5.0, posted_speed_kph=50.0,
    )
    cfg = SpeedViolationConfig(calibration=cal)
    tracker = CentroidTracker()
    events = []
    ts = 0.0
    for x in (0.2, 0.4, 0.6, 0.8):  # 5 m in 2 s = 9 kph: under the limit, no event
        tracked = tracker.update([det(x, 0.5)], ts)
        events += list(pack.evaluate(tracked, flow, cfg, window(ts)))
        ts += 1.0
    assert events == []


def test_speed_calibration_accepts_legacy_rectangle_gates() -> None:
    rect = {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1}
    cal = SpeedCalibrationConfig(gate_a=rect, gate_b=[])
    assert len(cal.gate_a) == 4


# ── moving object ─────────────────────────────────────────────────────────────


def test_moving_object_reports_tracked_people_with_direction() -> None:
    pack = MovingObjectPack()
    tracker = CentroidTracker()
    cfg = MovingObjectConfig(min_observations=2)
    flow = FlowWindow(camera_id="cam")
    first = tracker.update([det(0.5, 0.5, VehicleClass.pedestrian)], 1.0)
    assert list(pack.evaluate(first, flow, cfg, window(1.0))) == []  # one observation only
    second = tracker.update([det(0.5, 0.45, VehicleClass.pedestrian)], 2.0)
    events = list(pack.evaluate(second, flow, cfg, window(2.0)))
    assert len(events) == 1
    assert events[0].direction.compass == "N"
    assert events[0].track_id == second[0].track_id
    assert "walking" in events[0].person_descriptor or "stationary" in events[0].person_descriptor


def test_moving_object_zone_filter() -> None:
    pack = MovingObjectPack()
    zone = [[0.0, 0.0], [0.3, 0.0], [0.3, 0.3], [0.0, 0.3]]
    cfg = MovingObjectConfig(min_observations=1, zone=zone)
    flow = FlowWindow(camera_id="cam")
    out = list(pack.evaluate([det(0.8, 0.8, VehicleClass.pedestrian)], flow, cfg, window(1)))
    assert out == []


# ── runner ────────────────────────────────────────────────────────────────────


def test_pack_runner_builds_configs_from_store_rows_and_debounces() -> None:
    runner = PackRunner("cam")
    runner.configure(
        bindings=[{"pack_id": "moving_object", "parameters": '{"min_observations": 1}',
                   "report_interval_seconds": 5}],
        stop_zone=None,
        calibration=None,
    )
    assert runner.active_packs == ["moving_object"]
    frame = InferenceFrame(
        frame_id="f1", camera_id="cam", timestamp_ms=int(time.time() * 1000), width=640, height=360,
        detections=[det(0.5, 0.5, VehicleClass.pedestrian)],
    )
    first = runner.process(frame)
    assert len(first) == 1 and first[0][0] == "moving_object"
    # Same person a moment later: debounced by the 5 s report interval.
    again = runner.process(frame.model_copy(update={"frame_id": "f2"}))
    assert again == []
    assert runner.status()["tracks"] == 1


def test_pack_runner_with_stop_zone_from_store_json() -> None:
    runner = PackRunner("cam")
    runner.configure(
        bindings=[
            {"pack_id": PackId.stop_sign.value, "parameters": {}, "report_interval_seconds": 2}
        ],
        stop_zone={
            "polygon": "[[0.4,0.4],[0.6,0.4],[0.6,0.6],[0.4,0.6]]",
            "approach_direction": "N",
            "compliance_thresholds": '{"dwell_threshold_ms": 500}',
        },
        calibration=None,
    )
    cfg = runner._configs[PackId.stop_sign]
    assert isinstance(cfg, StopSignConfig)
    assert cfg.stop_zone is not None and len(cfg.stop_zone.polygon) == 4
    assert cfg.dwell_threshold_ms == 500
