from __future__ import annotations
import time
from dataclasses import dataclass, field


@dataclass
class AnalyticsMetrics:
    frames_processed: int = 0
    total_detections: int = 0
    congestion_events: int = 0
    traffic_events_emitted: int = 0
    _start_time: float = field(default_factory=time.time)

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self._start_time

    @property
    def frames_per_second(self) -> float:
        elapsed = self.elapsed_seconds
        return self.frames_processed / elapsed if elapsed > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "frames_processed": self.frames_processed,
            "total_detections": self.total_detections,
            "congestion_events": self.congestion_events,
            "traffic_events_emitted": self.traffic_events_emitted,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "frames_per_second": round(self.frames_per_second, 2),
        }
