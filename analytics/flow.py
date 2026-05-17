from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field

from vision.schemas import InferenceFrame, VehicleClass


@dataclass
class FlowWindow:
    camera_id: str
    window_size: int = 30
    congestion_threshold: int = 10
    _frames: deque = field(default_factory=deque)

    def push(self, frame: InferenceFrame) -> None:
        self._frames.append(frame)
        if len(self._frames) > self.window_size:
            self._frames.popleft()

    @property
    def vehicle_count(self) -> int:
        if not self._frames:
            return 0
        return sum(
            1 for d in self._frames[-1].detections
            if d.vehicle_class != VehicleClass.pedestrian
        )

    @property
    def is_congested(self) -> bool:
        return self.vehicle_count >= self.congestion_threshold

    @property
    def mean_inference_latency_ms(self) -> float | None:
        latencies = [
            f.inference_latency_ms
            for f in self._frames
            if f.inference_latency_ms is not None
        ]
        if not latencies:
            return None
        return sum(latencies) / len(latencies)

    def class_counts(self) -> dict[str, int]:
        if not self._frames:
            return {}
        counts: dict[str, int] = {}
        for d in self._frames[-1].detections:
            counts[d.vehicle_class.value] = counts.get(d.vehicle_class.value, 0) + 1
        return counts
