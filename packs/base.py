from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel

from analytics.flow import FlowWindow
from events.schemas import TrafficEvent
from vision.schemas import VehicleDetection


class PackId(StrEnum):
    moving_object = "moving_object"
    speed_violation = "speed_violation"
    stop_sign = "stop_sign"


@dataclass
class ReportWindow:
    """Carries timing context into a pack's evaluate() call."""

    camera_id: str
    report_interval_seconds: int
    now_ts: float  # time.time() at call time


class Pack(Protocol):
    pack_id: PackId
    version: str
    parameters: type[BaseModel]
    requires: set[str]

    def evaluate(
        self,
        detections: list[VehicleDetection],
        flow: FlowWindow,
        config: BaseModel,
        window: ReportWindow,
    ) -> Iterable[TrafficEvent]: ...
