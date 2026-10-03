"""Per-camera pack execution: tracker → bound packs → debounce → events.

``PackRunner`` is fed one inferred frame at a time by the camera runtime. It
holds the tracker and pack state for a camera, builds each pack's config from
the stored binding parameters plus the camera's stop zone / speed calibration,
and returns the events that should be persisted.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from pydantic import BaseModel

from analytics.flow import FlowWindow
from events.reporter import EventReporter
from events.schemas import TrafficEvent
from packs.base import PackId, ReportWindow
from packs.moving_object import MovingObjectPack
from packs.speed_violation import SpeedCalibrationConfig, SpeedViolationConfig, SpeedViolationPack
from packs.stop_sign import StopSignConfig, StopSignPack, StopZone
from packs.tracking import CentroidTracker
from packs.vehicle_count import VehicleCountConfig, VehicleCountPack
from vision.schemas import InferenceFrame

logger = logging.getLogger(__name__)


class PackRunner:
    def __init__(self, camera_id: str) -> None:
        self.camera_id = camera_id
        self.tracker = CentroidTracker()
        self.flow = FlowWindow(camera_id=camera_id)
        self.reporter = EventReporter()
        self._packs: dict[PackId, Any] = {
            PackId.moving_object: MovingObjectPack(),
            PackId.speed_violation: SpeedViolationPack(),
            PackId.stop_sign: StopSignPack(),
            PackId.vehicle_count: VehicleCountPack(),
        }
        self._bindings: list[dict[str, Any]] = []
        self._stop_zone: dict[str, Any] | None = None
        self._calibration: dict[str, Any] | None = None
        self._configs: dict[PackId, BaseModel] = {}
        self.events_emitted = 0
        self.last_error: str | None = None

    # ── configuration ─────────────────────────────────────────────────────────

    def configure(
        self,
        bindings: list[dict[str, Any]],
        stop_zone: dict[str, Any] | None,
        calibration: dict[str, Any] | None,
    ) -> None:
        self._bindings = [dict(b) for b in bindings]
        self._stop_zone = stop_zone
        self._calibration = calibration
        self._configs = {}
        for binding in self._bindings:
            try:
                pack_id = PackId(str(binding["pack_id"]))
            except ValueError:
                continue
            params = binding.get("parameters")
            if isinstance(params, str):
                params = json.loads(params or "{}")
            params = dict(params or {})
            self._configs[pack_id] = self._build_config(pack_id, params)
        for pack_id, pack in self._packs.items():
            if pack_id not in self._configs and hasattr(pack, "reset"):
                pack.reset()

    def _build_config(self, pack_id: PackId, params: dict[str, Any]) -> BaseModel:
        if pack_id == PackId.stop_sign:
            zone = None
            if self._stop_zone:
                polygon = self._stop_zone.get("polygon")
                if isinstance(polygon, str):
                    polygon = json.loads(polygon or "[]")
                zone = StopZone(
                    polygon=polygon or [],
                    approach_direction=str(self._stop_zone.get("approach_direction", "N")),
                )
                thresholds = self._stop_zone.get("compliance_thresholds") or {}
                if isinstance(thresholds, str):
                    thresholds = json.loads(thresholds or "{}")
                params = {**thresholds, **params}
            return StopSignConfig(stop_zone=zone, **_known(StopSignConfig, params))
        if pack_id == PackId.speed_violation:
            cal = None
            if self._calibration:
                cal_data = dict(self._calibration)
                for key in ("gate_a", "gate_b"):
                    value = cal_data.get(key)
                    if isinstance(value, str):
                        cal_data[key] = json.loads(value or "[]")
                cal = SpeedCalibrationConfig(**_known(SpeedCalibrationConfig, cal_data))
            return SpeedViolationConfig(calibration=cal, **_known(SpeedViolationConfig, params))
        if pack_id == PackId.vehicle_count:
            return VehicleCountConfig(**_known(VehicleCountConfig, params))
        return MovingObjectPack.parameters(**_known(MovingObjectPack.parameters, params))

    @property
    def active_packs(self) -> list[str]:
        return [str(p) for p in self._configs]

    # ── evaluation ────────────────────────────────────────────────────────────

    def process(self, frame: InferenceFrame) -> list[tuple[str, TrafficEvent]]:
        """Run bound packs on an inferred frame. Returns (pack_id, event) pairs."""
        now_ts = time.time()
        tracked = self.tracker.update(list(frame.detections), now_ts)
        tracked_frame = frame.model_copy(update={"detections": tracked})
        self.flow.push(tracked_frame)
        emitted: list[tuple[str, TrafficEvent]] = []
        if not self._configs:
            return emitted
        for pack_id, config in self._configs.items():
            pack = self._packs[pack_id]
            interval = next(
                (
                    int(b.get("report_interval_seconds", 5))
                    for b in self._bindings
                    if str(b.get("pack_id")) == str(pack_id)
                ),
                5,
            )
            window = ReportWindow(
                camera_id=self.camera_id, report_interval_seconds=interval, now_ts=now_ts
            )
            try:
                events = list(pack.evaluate(tracked, self.flow, config, window))
                for lost in self.tracker.lost:
                    if hasattr(pack, "on_track_lost"):
                        events.extend(pack.on_track_lost(lost.track_id, config, window))
                        self.reporter.clear_track(self.camera_id, lost.track_id, str(pack_id))
            except Exception as exc:  # pragma: no cover - pack bugs must not kill the loop
                self.last_error = f"{pack_id}: {exc}"
                logger.exception("pack %s failed on camera %s", pack_id, self.camera_id)
                continue
            for event in self.reporter.filter(events, str(pack_id), interval):
                emitted.append((str(pack_id), event))
        self.events_emitted += len(emitted)
        return emitted

    def tracked_frame(self, frame: InferenceFrame) -> InferenceFrame:
        return frame

    def status(self) -> dict[str, Any]:
        return {
            "active_packs": self.active_packs,
            "tracks": len(self.tracker.tracks),
            "events_emitted": self.events_emitted,
            "last_error": self.last_error,
        }


def _known(model: type[BaseModel], params: dict[str, Any]) -> dict[str, Any]:
    fields = set(model.model_fields)
    return {k: v for k, v in params.items() if k in fields}
