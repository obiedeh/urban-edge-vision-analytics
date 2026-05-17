from __future__ import annotations
import random
import time
import uuid
from abc import ABC, abstractmethod

from .schemas import BoundingBox, InferenceFrame, VehicleClass, VehicleDetection


class DetectionAdapter(ABC):
    @abstractmethod
    def infer(self, frame: InferenceFrame) -> InferenceFrame:
        ...


class MockDetectionAdapter(DetectionAdapter):
    """Deterministic mock that produces synthetic detections without any model dependency."""

    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)

    def infer(self, frame: InferenceFrame) -> InferenceFrame:
        start = time.perf_counter()
        n = self._rng.randint(0, 4)
        detections = [
            VehicleDetection(
                track_id=str(uuid.uuid4())[:8],
                vehicle_class=self._rng.choice(list(VehicleClass)),
                bounding_box=BoundingBox(
                    x=self._rng.uniform(0, frame.width * 0.8),
                    y=self._rng.uniform(0, frame.height * 0.8),
                    width=self._rng.uniform(30, 150),
                    height=self._rng.uniform(30, 100),
                    confidence=self._rng.uniform(0.5, 0.99),
                ),
                frame_id=frame.frame_id,
                timestamp_ms=frame.timestamp_ms,
            )
            for _ in range(n)
        ]
        latency_ms = (time.perf_counter() - start) * 1000
        return frame.model_copy(update={"detections": detections, "inference_latency_ms": latency_ms})
