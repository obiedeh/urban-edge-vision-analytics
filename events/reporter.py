from __future__ import annotations

import time
from collections.abc import Iterable

from events.schemas import TrafficEvent

# Terminal event types that bypass the debounce floor (emit immediately on
# finalize regardless of when the last report was sent).
_TERMINAL_EVENT_TYPES: set[str] = {
    # Pack 2/3 decision finalize — always emit once
    "speed_violation",
    "stop_sign_violation",
}


class EventReporter:
    """Debouncer keyed by (camera_id, track_id, pack_id).

    Pack 1 (continuous): suppresses duplicate reports within report_interval_seconds
    while a track is alive; terminal events (track_loss) bypass the floor.

    Packs 2 & 3 (decisional): the event fires once on decision finalize. The
    interval acts as a debounce floor for repeated decisions on the same track_id
    within a short time window.

    Hard floor: report_interval_seconds is always treated as >= 2.
    """

    def __init__(self) -> None:
        # key: (camera_id, track_id, pack_id) → last emit timestamp
        self._last_emit: dict[tuple[str, str, str], float] = {}

    def filter(
        self,
        events: Iterable[TrafficEvent],
        pack_id: str,
        report_interval_seconds: int,
    ) -> list[TrafficEvent]:
        """Return only the events that should be emitted per the debounce rules."""
        interval = max(2, report_interval_seconds)
        now = time.time()
        result: list[TrafficEvent] = []
        for event in events:
            track_id = getattr(event, "track_id", event.event_id)
            key = (event.camera_id, track_id, pack_id)
            is_terminal = event.event_type in _TERMINAL_EVENT_TYPES
            last = self._last_emit.get(key)
            if is_terminal or last is None or (now - last) >= interval:
                result.append(event)
                self._last_emit[key] = now
        return result

    def clear_track(self, camera_id: str, track_id: str, pack_id: str) -> None:
        """Remove debounce state for a track that has left the frame."""
        self._last_emit.pop((camera_id, track_id, pack_id), None)

    def reset(self) -> None:
        """Clear all state (useful in tests)."""
        self._last_emit.clear()
