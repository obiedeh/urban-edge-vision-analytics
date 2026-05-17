from __future__ import annotations
import time
from dataclasses import dataclass


@dataclass
class RuntimeSnapshot:
    started_at: float = 0.0
    camera_count: int = 0
    event_count: int = 0
    incident_count: int = 0

    def since_start(self) -> float:
        return time.time() - self.started_at if self.started_at else 0.0

    def to_dict(self) -> dict:
        return {
            "uptime_seconds": round(self.since_start(), 2),
            "camera_count": self.camera_count,
            "event_count": self.event_count,
            "incident_count": self.incident_count,
        }
