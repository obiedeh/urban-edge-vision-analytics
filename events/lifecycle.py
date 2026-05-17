from __future__ import annotations
import uuid
from datetime import datetime, timezone

from .schemas import IntersectionIncident, IncidentStatus, Severity, TrafficEvent


class EventStore:
    def __init__(self) -> None:
        self._events: dict[str, TrafficEvent] = {}
        self._incidents: dict[str, IntersectionIncident] = {}

    def add_event(self, event: TrafficEvent) -> None:
        self._events[event.event_id] = event

    def get_event(self, event_id: str) -> TrafficEvent | None:
        return self._events.get(event_id)

    def list_events(self, camera_id: str | None = None) -> list[TrafficEvent]:
        events = list(self._events.values())
        if camera_id:
            events = [e for e in events if e.camera_id == camera_id]
        return sorted(events, key=lambda e: e.timestamp, reverse=True)

    def open_incident(
        self,
        camera_id: str,
        event_ids: list[str],
        severity: Severity,
        summary: str = "",
    ) -> IntersectionIncident:
        now = datetime.now(timezone.utc)
        incident = IntersectionIncident(
            incident_id=str(uuid.uuid4()),
            camera_id=camera_id,
            event_ids=event_ids,
            severity=severity,
            summary=summary,
            created_at=now,
            updated_at=now,
        )
        self._incidents[incident.incident_id] = incident
        return incident

    def update_incident_status(
        self, incident_id: str, status: IncidentStatus, notes: str = ""
    ) -> IntersectionIncident | None:
        incident = self._incidents.get(incident_id)
        if not incident:
            return None
        updated = incident.model_copy(update={
            "status": status,
            "operator_notes": notes,
            "updated_at": datetime.now(timezone.utc),
        })
        self._incidents[incident_id] = updated
        return updated

    def list_incidents(self, status: IncidentStatus | None = None) -> list[IntersectionIncident]:
        incidents = list(self._incidents.values())
        if status:
            incidents = [i for i in incidents if i.status == status]
        return sorted(incidents, key=lambda i: i.created_at, reverse=True)
