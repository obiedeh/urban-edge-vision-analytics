"""Vehicle counting on an operator-drawn count line.

Each tracked vehicle is counted once when its ground point crosses the line
segment, with the crossing direction (``a_to_b`` / ``b_to_a`` relative to the
drawn A→B line) and the operator's labels for the two directions. Counts are
records, not review items. Double counting is prevented per track: a track
that has been counted is remembered until it is lost; a vehicle that jitters
back and forth over the line produces one record, not two.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from analytics.flow import FlowWindow
from events.schemas import Direction, EventType, Severity, VehicleCountEvent, VehicleType
from packs.geometry import bottom_center, compass_from_vector, side_of_line
from vision.schemas import VehicleClass, VehicleDetection

from .base import PackId, ReportWindow

_CLASS_MAP: dict[VehicleClass, VehicleType] = {
    VehicleClass.car: VehicleType.car,
    VehicleClass.truck: VehicleType.truck,
    VehicleClass.motorcycle: VehicleType.motorcycle,
    VehicleClass.bus: VehicleType.bus,
}

COUNTED_CLASSES: tuple[str, ...] = ("car", "truck", "bus", "motorcycle")


class VehicleCountConfig(BaseModel):
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    # Two points, normalised 0..1, drawn A → B in Studio.
    count_line: list[list[float]] = Field(default_factory=list)
    classes: list[str] = Field(default_factory=lambda: list(COUNTED_CLASSES))
    label_a_to_b: str = "a_to_b"
    label_b_to_a: str = "b_to_a"
    # Require at least this many observations so a single spurious box never counts.
    min_observations: int = Field(default=2, ge=1)


class VehicleCountPack:
    pack_id = PackId.vehicle_count
    version = "1.0.0"
    parameters = VehicleCountConfig
    requires: set[str] = {"count_line"}

    def __init__(self) -> None:
        self._last_side: dict[str, float] = {}
        self._counted: set[str] = set()

    def reset(self) -> None:
        self._last_side.clear()
        self._counted.clear()

    def evaluate(
        self,
        detections: list[VehicleDetection],
        flow: FlowWindow,
        config: BaseModel,
        window: ReportWindow,
    ) -> Iterable[VehicleCountEvent]:
        cfg = config if isinstance(config, VehicleCountConfig) else VehicleCountConfig()
        if len(cfg.count_line) < 2:
            return
        a, b = cfg.count_line[0], cfg.count_line[1]
        classes = {c.lower() for c in cfg.classes}
        for det in detections:
            if det.vehicle_class.value not in classes or det.vehicle_class not in _CLASS_MAP:
                continue
            if det.bounding_box.confidence < cfg.confidence_threshold:
                continue
            bb = det.bounding_box
            point = bottom_center(bb.x, bb.y, bb.width, bb.height)
            side = side_of_line(point, a, b)
            prev = self._last_side.get(det.track_id)
            self._last_side[det.track_id] = side
            if prev is None or side == 0 or prev == 0 or (prev > 0) == (side > 0):
                continue
            if det.track_id in self._counted:
                continue
            track = det.metadata.get("track", {}) if isinstance(det.metadata, dict) else {}
            if int(track.get("observations", 1)) < cfg.min_observations:
                continue
            if not _within_segment(point, a, b):
                continue
            self._counted.add(det.track_id)
            crossing: Literal["a_to_b", "b_to_a"] = "a_to_b" if prev > 0 else "b_to_a"
            label = cfg.label_a_to_b if crossing == "a_to_b" else cfg.label_b_to_a
            now = datetime.now(UTC)
            yield VehicleCountEvent(
                event_id=str(uuid.uuid4()),
                camera_id=window.camera_id,
                event_type=EventType.vehicle_count,
                severity=Severity.info,
                operator_review_recommended=False,
                timestamp=now,
                confidence=bb.confidence,
                vehicle_count=1,
                track_ids=[det.track_id],
                vehicle_type=_CLASS_MAP[det.vehicle_class],
                crossing=crossing,
                direction_label=label,
                direction=Direction(
                    compass=compass_from_vector(
                        float(track.get("vx", 0.0)), float(track.get("vy", 0.0))
                    )
                ),
                track_id=det.track_id,
                counted_at=now,
                metadata={"point": [round(point[0], 4), round(point[1], 4)]},
            )

    def on_track_lost(
        self, track_id: str, config: BaseModel, window: ReportWindow
    ) -> Iterable[VehicleCountEvent]:
        self._last_side.pop(track_id, None)
        self._counted.discard(track_id)
        return ()


def _within_segment(point: tuple[float, float], a: list[float], b: list[float]) -> bool:
    """The crossing must happen within the drawn segment (with a small margin)."""
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    seg_len_sq = (bx - ax) ** 2 + (by - ay) ** 2 or 1e-12
    u = ((point[0] - ax) * (bx - ax) + (point[1] - ay) * (by - ay)) / seg_len_sq
    return -0.05 <= u <= 1.05
