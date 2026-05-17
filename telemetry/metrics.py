from __future__ import annotations
import statistics
from dataclasses import dataclass, field


@dataclass
class InferenceMetrics:
    _latencies_ms: list[float] = field(default_factory=list)
    frames_dropped: int = 0

    def record(self, latency_ms: float) -> None:
        self._latencies_ms.append(latency_ms)

    @property
    def sample_count(self) -> int:
        return len(self._latencies_ms)

    @property
    def mean_ms(self) -> float | None:
        return statistics.mean(self._latencies_ms) if self._latencies_ms else None

    @property
    def p95_ms(self) -> float | None:
        if not self._latencies_ms:
            return None
        s = sorted(self._latencies_ms)
        return s[min(int(len(s) * 0.95), len(s) - 1)]

    @property
    def p99_ms(self) -> float | None:
        if not self._latencies_ms:
            return None
        s = sorted(self._latencies_ms)
        return s[min(int(len(s) * 0.99), len(s) - 1)]

    def to_dict(self) -> dict:
        return {
            "sample_count": self.sample_count,
            "mean_ms": round(self.mean_ms, 3) if self.mean_ms is not None else None,
            "p95_ms": round(self.p95_ms, 3) if self.p95_ms is not None else None,
            "p99_ms": round(self.p99_ms, 3) if self.p99_ms is not None else None,
            "frames_dropped": self.frames_dropped,
        }
