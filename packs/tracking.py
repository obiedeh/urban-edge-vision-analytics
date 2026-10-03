"""Frame-to-frame association so packs can reason about dwell, gates and motion.

Detections arrive once per inference interval (typically 0.25–2 s) with fresh
random ids. ``CentroidTracker`` greedily matches them to live tracks by IoU,
falling back to centroid distance, and rewrites ``track_id`` to a stable id.
Per-track kinematics (velocity in frame-widths per second, age, trail) are
attached under ``metadata["track"]``. All coordinates are normalised 0..1.
"""
from __future__ import annotations

import itertools
from collections import deque
from dataclasses import dataclass, field

from packs.geometry import bottom_center, centroid
from vision.schemas import VehicleClass, VehicleDetection


@dataclass
class Track:
    track_id: str
    vehicle_class: VehicleClass
    x: float
    y: float
    w: float
    h: float
    first_ts: float
    last_ts: float
    misses: int = 0
    trail: deque[tuple[float, float, float]] = field(default_factory=lambda: deque(maxlen=30))

    @property
    def center(self) -> tuple[float, float]:
        return centroid(self.x, self.y, self.w, self.h)

    @property
    def ground(self) -> tuple[float, float]:
        return bottom_center(self.x, self.y, self.w, self.h)

    def velocity(self, window_s: float = 2.0) -> tuple[float, float]:
        """Mean velocity over the recent trail, in unit-square per second."""
        if len(self.trail) < 2:
            return (0.0, 0.0)
        t_end, x_end, y_end = self.trail[-1]
        start = next((p for p in self.trail if t_end - p[0] <= window_s), self.trail[0])
        if start[0] == t_end:
            start = self.trail[-2]
        t0, x0, y0 = start
        dt = t_end - t0
        if dt <= 0:
            return (0.0, 0.0)
        return ((x_end - x0) / dt, (y_end - y0) / dt)

    @property
    def speed(self) -> float:
        vx, vy = self.velocity()
        return (vx * vx + vy * vy) ** 0.5


def _iou(a: Track, bx: float, by: float, bw: float, bh: float) -> float:
    ix1, iy1 = max(a.x, bx), max(a.y, by)
    ix2, iy2 = min(a.x + a.w, bx + bw), min(a.y + a.h, by + bh)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    union = a.w * a.h + bw * bh - inter
    return inter / union if union > 0 else 0.0


class CentroidTracker:
    def __init__(
        self,
        *,
        iou_threshold: float = 0.15,
        distance_threshold: float = 0.3,
        max_misses: int = 3,
    ) -> None:
        self._tracks: dict[str, Track] = {}
        self._ids = itertools.count(1)
        self.iou_threshold = iou_threshold
        self.distance_threshold = distance_threshold
        self.max_misses = max_misses
        self.lost: list[Track] = []

    @property
    def tracks(self) -> dict[str, Track]:
        return self._tracks

    def update(self, detections: list[VehicleDetection], ts: float) -> list[VehicleDetection]:
        self.lost = []
        unmatched = list(self._tracks.values())
        out: list[VehicleDetection] = []
        # Greedy: best IoU first, then nearest centroid of the same class.
        pairs: list[tuple[float, int, Track]] = []
        for i, det in enumerate(detections):
            bb = det.bounding_box
            for track in unmatched:
                if not _compatible(track.vehicle_class, det.vehicle_class):
                    continue
                score = _iou(track, bb.x, bb.y, bb.width, bb.height)
                if score < self.iou_threshold:
                    cx, cy = centroid(bb.x, bb.y, bb.width, bb.height)
                    tx, ty = track.center
                    dist = ((cx - tx) ** 2 + (cy - ty) ** 2) ** 0.5
                    if dist > self.distance_threshold:
                        continue
                    score = 0.001 + (self.distance_threshold - dist) / self.distance_threshold * 0.1
                pairs.append((score, i, track))
        pairs.sort(key=lambda p: p[0], reverse=True)
        assigned_dets: set[int] = set()
        assigned_tracks: set[str] = set()
        for _, i, track in pairs:
            if i in assigned_dets or track.track_id in assigned_tracks:
                continue
            assigned_dets.add(i)
            assigned_tracks.add(track.track_id)
            out.append(self._advance(track, detections[i], ts))
        for i, det in enumerate(detections):
            if i in assigned_dets:
                continue
            bb = det.bounding_box
            track = Track(
                track_id=f"t{next(self._ids)}",
                vehicle_class=det.vehicle_class,
                x=bb.x, y=bb.y, w=bb.width, h=bb.height,
                first_ts=ts, last_ts=ts,
            )
            self._tracks[track.track_id] = track
            out.append(self._advance(track, det, ts))
        for track in list(self._tracks.values()):
            if track.track_id in assigned_tracks or track.last_ts == ts:
                continue
            track.misses += 1
            if track.misses > self.max_misses:
                self.lost.append(self._tracks.pop(track.track_id))
        return out

    def _advance(self, track: Track, det: VehicleDetection, ts: float) -> VehicleDetection:
        bb = det.bounding_box
        track.x, track.y, track.w, track.h = bb.x, bb.y, bb.width, bb.height
        track.last_ts = ts
        track.misses = 0
        if det.vehicle_class != VehicleClass.unknown:
            track.vehicle_class = det.vehicle_class
        cx, cy = track.ground
        track.trail.append((ts, cx, cy))
        vx, vy = track.velocity()
        return det.model_copy(
            update={
                "track_id": track.track_id,
                "vehicle_class": track.vehicle_class,
                "metadata": {
                    **det.metadata,
                    "track": {
                        "age_s": round(ts - track.first_ts, 2),
                        "vx": round(vx, 4),
                        "vy": round(vy, 4),
                        "speed": round(track.speed, 4),
                        "observations": len(track.trail),
                    },
                },
            }
        )


def _compatible(a: VehicleClass, b: VehicleClass) -> bool:
    if a == b or VehicleClass.unknown in (a, b):
        return True
    people = {VehicleClass.pedestrian, VehicleClass.cyclist}
    return (a in people) == (b in people)
