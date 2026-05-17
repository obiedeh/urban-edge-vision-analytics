import uuid
from datetime import datetime, timezone

import pytest

from events.lifecycle import EventStore
from events.schemas import EventType, IncidentStatus, Severity, TrafficEvent


def _make_event(camera_id: str = "cam-001", event_type: EventType = EventType.vehicle_detected) -> TrafficEvent:
    return TrafficEvent(
        event_id=str(uuid.uuid4()),
        camera_id=camera_id,
        event_type=event_type,
        severity=Severity.info,
        timestamp=datetime.now(timezone.utc),
    )


def test_add_and_get_event():
    store = EventStore()
    event = _make_event()
    store.add_event(event)
    assert store.get_event(event.event_id) == event


def test_get_missing_event():
    store = EventStore()
    assert store.get_event("nonexistent") is None


def test_list_events_by_camera():
    store = EventStore()
    e1 = _make_event(camera_id="cam-001")
    e2 = _make_event(camera_id="cam-002")
    store.add_event(e1)
    store.add_event(e2)
    results = store.list_events(camera_id="cam-001")
    assert len(results) == 1
    assert results[0].camera_id == "cam-001"


def test_open_incident():
    store = EventStore()
    event = _make_event()
    store.add_event(event)
    incident = store.open_incident(
        camera_id="cam-001",
        event_ids=[event.event_id],
        severity=Severity.warning,
        summary="Test incident",
    )
    assert incident.status == IncidentStatus.open
    assert incident.summary == "Test incident"
    assert event.event_id in incident.event_ids


def test_update_incident_status():
    store = EventStore()
    event = _make_event()
    store.add_event(event)
    incident = store.open_incident(
        camera_id="cam-001",
        event_ids=[event.event_id],
        severity=Severity.warning,
    )
    updated = store.update_incident_status(
        incident.incident_id, IncidentStatus.resolved, notes="Reviewed and closed"
    )
    assert updated.status == IncidentStatus.resolved
    assert updated.operator_notes == "Reviewed and closed"


def test_update_missing_incident():
    store = EventStore()
    assert store.update_incident_status("nonexistent", IncidentStatus.resolved) is None


def test_list_incidents_by_status():
    store = EventStore()
    event = _make_event()
    store.add_event(event)
    inc = store.open_incident("cam-001", [event.event_id], Severity.info)
    store.update_incident_status(inc.incident_id, IncidentStatus.resolved)
    open_incidents = store.list_incidents(status=IncidentStatus.open)
    assert len(open_incidents) == 0
