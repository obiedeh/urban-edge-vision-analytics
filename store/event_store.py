"""SQLite-backed event and incident store (replaces the in-memory EventStore).

Synchronous ``sqlite3`` behind a lock: callers are FastAPI sync routes (run in
the threadpool) and the camera runtime (one short insert per event). Full
event payloads are stored as JSON so pack-specific fields survive a restart.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from events.schemas import IncidentStatus, IntersectionIncident, Severity, TrafficEvent

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

REVIEW_STATUSES = ("none", "pending", "confirmed", "dismissed")


class SqliteEventStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._db_path, timeout=10, check_same_thread=False)
        db.row_factory = sqlite3.Row
        return db

    # ── Events ────────────────────────────────────────────────────────────────

    def add_event(self, event: TrafficEvent, *, pack_id: str | None = None) -> dict[str, Any]:
        payload = event.model_dump(mode="json")
        if pack_id:
            payload["pack_id"] = pack_id
        review_status = "pending" if event.operator_review_recommended else "none"
        payload["review_status"] = review_status
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO events
                    (event_id, camera_id, event_type, severity, timestamp, pack_id,
                     operator_review_recommended, review_status, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.camera_id,
                    event.event_type.value,
                    event.severity.value,
                    event.timestamp.isoformat(),
                    pack_id,
                    1 if event.operator_review_recommended else 0,
                    review_status,
                    json.dumps(payload),
                ),
            )
        return payload

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
        return _event_row(row) if row else None

    def list_events(
        self,
        camera_id: str | None = None,
        *,
        limit: int = 50,
        before: str | None = None,
        review_only: bool = False,
        review_status: str | None = None,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if camera_id:
            clauses.append("camera_id = ?")
            params.append(camera_id)
        if before:
            clauses.append("timestamp < ?")
            params.append(before)
        if review_only:
            clauses.append("operator_review_recommended = 1")
        if review_status:
            clauses.append("review_status = ?")
            params.append(review_status)
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM events {where} ORDER BY timestamp DESC LIMIT ?",
                (*params, max(1, min(limit, 500))),
            ).fetchall()
        return [_event_row(r) for r in rows]

    def count_events(self, camera_id: str | None = None) -> int:
        with self._lock, self._connect() as db:
            if camera_id:
                row = db.execute(
                    "SELECT COUNT(*) FROM events WHERE camera_id = ?", (camera_id,)
                ).fetchone()
            else:
                row = db.execute("SELECT COUNT(*) FROM events").fetchone()
        return int(row[0]) if row else 0

    def review_event(self, event_id: str, status: str, note: str = "") -> dict[str, Any] | None:
        if status not in REVIEW_STATUSES:
            raise ValueError(f"review status must be one of {REVIEW_STATUSES}")
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
            if not row:
                return None
            payload = json.loads(row["payload_json"])
            payload["review_status"] = status
            payload["review_note"] = note
            payload["reviewed_at"] = now
            db.execute(
                """
                UPDATE events SET review_status = ?, review_note = ?, reviewed_at = ?,
                                  payload_json = ?
                WHERE event_id = ?
                """,
                (status, note, now, json.dumps(payload), event_id),
            )
        return payload

    def review_counts(self) -> dict[str, int]:
        with self._lock, self._connect() as db:
            rows = db.execute(
                """
                SELECT review_status, COUNT(*) AS n FROM events
                WHERE operator_review_recommended = 1 GROUP BY review_status
                """
            ).fetchall()
        counts = {status: 0 for status in REVIEW_STATUSES if status != "none"}
        for row in rows:
            counts[row["review_status"]] = int(row["n"])
        return counts

    def delete_camera_events(self, camera_id: str) -> int:
        with self._lock, self._connect() as db:
            cur = db.execute("DELETE FROM events WHERE camera_id = ?", (camera_id,))
            return cur.rowcount

    # ── Incidents ─────────────────────────────────────────────────────────────

    def open_incident(
        self,
        camera_id: str,
        event_ids: list[str],
        severity: Severity,
        summary: str = "",
    ) -> IntersectionIncident:
        now = datetime.now(UTC)
        incident = IntersectionIncident(
            incident_id=str(uuid.uuid4()),
            camera_id=camera_id,
            event_ids=event_ids,
            severity=severity,
            summary=summary,
            created_at=now,
            updated_at=now,
        )
        self._write_incident(incident)
        return incident

    def update_incident_status(
        self, incident_id: str, status: IncidentStatus, notes: str = ""
    ) -> IntersectionIncident | None:
        incident = self.get_incident(incident_id)
        if not incident:
            return None
        updated = incident.model_copy(
            update={"status": status, "operator_notes": notes, "updated_at": datetime.now(UTC)}
        )
        self._write_incident(updated)
        return updated

    def get_incident(self, incident_id: str) -> IntersectionIncident | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT payload_json FROM incidents WHERE incident_id = ?", (incident_id,)
            ).fetchone()
        return IntersectionIncident.model_validate_json(row[0]) if row else None

    def list_incidents(self, status: IncidentStatus | None = None) -> list[IntersectionIncident]:
        with self._lock, self._connect() as db:
            if status:
                rows = db.execute(
                    "SELECT payload_json FROM incidents WHERE status = ? ORDER BY created_at DESC",
                    (status.value,),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT payload_json FROM incidents ORDER BY created_at DESC"
                ).fetchall()
        return [IntersectionIncident.model_validate_json(r[0]) for r in rows]

    def _write_incident(self, incident: IntersectionIncident) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO incidents
                    (incident_id, camera_id, status, created_at, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    incident.incident_id,
                    incident.camera_id,
                    incident.status.value,
                    incident.created_at.isoformat(),
                    incident.model_dump_json(),
                ),
            )


def _event_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(row["payload_json"])
    payload["review_status"] = row["review_status"]
    payload["review_note"] = row["review_note"]
    payload["reviewed_at"] = row["reviewed_at"]
    if row["pack_id"]:
        payload["pack_id"] = row["pack_id"]
    return payload
