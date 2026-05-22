"""Tests for EventReporter debounce logic — ≥ 90% coverage target."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from events.reporter import EventReporter
from events.schemas import EventType, Severity, TrafficEvent


def _event(
    camera_id: str = "cam-1",
    track_id: str = "t1",
    event_type: EventType = EventType.person_activity,
) -> TrafficEvent:
    from datetime import UTC, datetime

    return TrafficEvent(
        event_id="evt-1",
        camera_id=camera_id,
        event_type=event_type,
        severity=Severity.info,
        timestamp=datetime.now(UTC),
        track_ids=[track_id],
        metadata={"track_id": track_id},
    )


class _PersonEvent(TrafficEvent):
    """Simulates MovingObjectEvent with track_id attribute."""

    track_id: str

    model_config = {"extra": "allow"}


def _person_event(camera_id: str = "cam-1", track_id: str = "t1") -> _PersonEvent:
    from datetime import UTC, datetime

    return _PersonEvent(  # type: ignore[call-arg]
        event_id="evt-1",
        camera_id=camera_id,
        event_type=EventType.person_activity,
        severity=Severity.info,
        timestamp=datetime.now(UTC),
        track_id=track_id,
    )


@pytest.fixture
def reporter() -> EventReporter:
    return EventReporter()


def test_first_event_always_passes(reporter: EventReporter) -> None:
    events = reporter.filter([_person_event()], "moving_object", 5)
    assert len(events) == 1


def test_duplicate_within_interval_suppressed(reporter: EventReporter) -> None:
    now = time.time()
    with patch("events.reporter.time") as mock_time:
        mock_time.time.return_value = now
        reporter.filter([_person_event()], "moving_object", 5)
        # Same key, 1s later — within the 5s interval → suppressed
        mock_time.time.return_value = now + 1.0
        result = reporter.filter([_person_event()], "moving_object", 5)
    assert result == []


def test_event_passes_after_interval(reporter: EventReporter) -> None:
    now = time.time()
    with patch("events.reporter.time") as mock_time:
        mock_time.time.return_value = now
        reporter.filter([_person_event()], "moving_object", 5)
        mock_time.time.return_value = now + 6.0  # past the 5s interval
        result = reporter.filter([_person_event()], "moving_object", 5)
    assert len(result) == 1


def test_interval_floor_of_2(reporter: EventReporter) -> None:
    """report_interval_seconds=1 is silently promoted to 2."""
    now = time.time()
    with patch("events.reporter.time") as mock_time:
        mock_time.time.return_value = now
        reporter.filter([_person_event()], "moving_object", 1)
        mock_time.time.return_value = now + 1.5  # between 1s and 2s
        # With floor=2, this should still be suppressed
        result = reporter.filter([_person_event()], "moving_object", 1)
    assert result == []


def test_different_tracks_independent(reporter: EventReporter) -> None:
    now = time.time()
    with patch("events.reporter.time") as mock_time:
        mock_time.time.return_value = now
        e1 = _person_event(track_id="t1")
        e2 = _person_event(track_id="t2")
        results = reporter.filter([e1, e2], "moving_object", 5)
    assert len(results) == 2


def test_terminal_speed_violation_always_passes(reporter: EventReporter) -> None:
    """Speed violation events bypass the debounce (decisional — terminal)."""
    from datetime import UTC, datetime

    now = time.time()

    class _SpeedEv(TrafficEvent):
        track_id: str
        model_config = {"extra": "allow"}

    def _sp(track_id: str = "t1") -> _SpeedEv:
        return _SpeedEv(  # type: ignore[call-arg]
            event_id="ev",
            camera_id="cam-1",
            event_type=EventType.speed_violation,
            severity=Severity.warning,
            timestamp=datetime.now(UTC),
            track_id=track_id,
        )

    with patch("events.reporter.time") as mock_time:
        mock_time.time.return_value = now
        reporter.filter([_sp()], "speed_violation", 5)
        mock_time.time.return_value = now + 0.5  # well within interval
        result = reporter.filter([_sp()], "speed_violation", 5)
    assert len(result) == 1


def test_clear_track_resets_state(reporter: EventReporter) -> None:
    now = time.time()
    with patch("events.reporter.time") as mock_time:
        mock_time.time.return_value = now
        reporter.filter([_person_event(track_id="t1")], "moving_object", 10)
        reporter.clear_track("cam-1", "t1", "moving_object")
        mock_time.time.return_value = now + 0.1  # would be suppressed without clear
        result = reporter.filter([_person_event(track_id="t1")], "moving_object", 10)
    assert len(result) == 1


def test_reset_clears_all_state(reporter: EventReporter) -> None:
    now = time.time()
    with patch("events.reporter.time") as mock_time:
        mock_time.time.return_value = now
        reporter.filter([_person_event()], "moving_object", 10)
        reporter.reset()
        mock_time.time.return_value = now + 0.1
        result = reporter.filter([_person_event()], "moving_object", 10)
    assert len(result) == 1


def test_different_packs_independent(reporter: EventReporter) -> None:
    now = time.time()
    with patch("events.reporter.time") as mock_time:
        mock_time.time.return_value = now
        reporter.filter([_person_event()], "moving_object", 5)
        # Same camera+track but different pack → should pass
        mock_time.time.return_value = now + 0.1
        result = reporter.filter([_person_event()], "speed_violation", 5)
    assert len(result) == 1


def test_different_cameras_independent(reporter: EventReporter) -> None:
    now = time.time()
    with patch("events.reporter.time") as mock_time:
        mock_time.time.return_value = now
        e1 = _person_event(camera_id="cam-1")
        e2 = _person_event(camera_id="cam-2")
        results = reporter.filter([e1, e2], "moving_object", 5)
    assert len(results) == 2
