from __future__ import annotations

from datetime import UTC, datetime

from events.schemas import EventType, IncidentStatus, Severity, StopSignEvent, TrafficEvent
from store.event_store import SqliteEventStore


def _event(camera: str = "cam-1", review: bool = False, ts: datetime | None = None) -> TrafficEvent:
    return TrafficEvent(
        event_id=f"e-{camera}-{(ts or datetime.now(UTC)).timestamp()}",
        camera_id=camera,
        event_type=EventType.vehicle_detected,
        severity=Severity.warning if review else Severity.info,
        timestamp=ts or datetime.now(UTC),
        operator_review_recommended=review,
    )


def test_events_persist_with_pack_fields(tmp_path) -> None:
    store = SqliteEventStore(str(tmp_path / "e.sqlite"))
    now = datetime.now(UTC)
    ev = StopSignEvent(
        event_id="s1", camera_id="cam", event_type=EventType.stop_sign_violation,
        severity=Severity.warning, timestamp=now, decision="no_stop", min_speed_in_zone=0.2,
        dwell_ms=0, vehicle_type="car", vehicle_color="unknown", vehicle_descriptor="car",
        direction={}, track_id="t1", detected_at=now, operator_review_recommended=True,
    )
    store.add_event(ev, pack_id="stop_sign")
    # A new store instance on the same file sees the row (persists across restart).
    again = SqliteEventStore(str(tmp_path / "e.sqlite"))
    got = again.get_event("s1")
    assert got and got["decision"] == "no_stop" and got["pack_id"] == "stop_sign"
    assert got["review_status"] == "pending"


def test_list_filters_and_review_queue(tmp_path) -> None:
    store = SqliteEventStore(str(tmp_path / "e.sqlite"))
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(5):
        store.add_event(_event("cam-1", review=(i % 2 == 0), ts=base.replace(minute=i)))
    store.add_event(_event("cam-2", ts=base.replace(hour=2)))
    assert len(store.list_events()) == 6
    assert len(store.list_events(camera_id="cam-2")) == 1
    newest_first = store.list_events(camera_id="cam-1")
    assert newest_first[0]["timestamp"] > newest_first[-1]["timestamp"]
    cutoff = base.replace(minute=2).isoformat()
    assert len(store.list_events(camera_id="cam-1", before=cutoff)) == 2
    assert store.review_counts() == {"pending": 3, "confirmed": 0, "dismissed": 0}
    pending = store.list_events(review_only=True, review_status="pending")
    assert len(pending) == 3
    reviewed = store.review_event(pending[0]["event_id"], "confirmed", "looks right")
    assert reviewed and reviewed["review_note"] == "looks right"
    assert store.review_counts()["confirmed"] == 1
    assert store.review_event("missing", "dismissed") is None
    assert store.count_events("cam-1") == 5


def test_incidents_round_trip(tmp_path) -> None:
    store = SqliteEventStore(str(tmp_path / "e.sqlite"))
    inc = store.open_incident("cam", ["e1"], Severity.critical, "summary")
    assert store.get_incident(inc.incident_id) == inc
    updated = store.update_incident_status(inc.incident_id, IncidentStatus.resolved, "done")
    assert updated and updated.status == IncidentStatus.resolved
    resolved = store.list_incidents(IncidentStatus.resolved)
    assert [i.incident_id for i in resolved] == [inc.incident_id]
    assert store.list_incidents(IncidentStatus.open) == []
    assert store.update_incident_status("missing", IncidentStatus.resolved) is None
