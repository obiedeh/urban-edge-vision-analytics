"""Publisher interface for shipping edge outputs to a cloud tier (Phase 0).

Payloads are always serialized from the Pydantic contract models
(``TrafficEvent``, ``IntersectionIncident``, ``EdgeTelemetry``) via
``model_dump(mode="json")`` and wrapped in a ``CloudEnvelope``. Publishers
never raise into the caller: a failed publish is logged and dropped, so the
vision loop and the operator API keep working without a network.
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Literal

from pydantic import BaseModel, Field

from events.schemas import IntersectionIncident, TrafficEvent
from telemetry.schemas import EdgeTelemetry

logger = logging.getLogger(__name__)

EnvelopeKind = Literal["event", "telemetry", "incident"]


class CloudEnvelope(BaseModel):
    """Wire format for every message an edge node publishes."""

    schema_version: int
    thing_name: str
    sent_at: datetime
    kind: EnvelopeKind
    payload: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def wrap(
        cls,
        kind: EnvelopeKind,
        model: BaseModel,
        *,
        thing_name: str,
        schema_version: int,
        sent_at: datetime | None = None,
    ) -> CloudEnvelope:
        return cls(
            schema_version=schema_version,
            thing_name=thing_name,
            sent_at=sent_at or datetime.now(UTC),
            kind=kind,
            payload=model.model_dump(mode="json"),
        )


class EventPublisher(ABC):
    """Abstract publisher. Subclasses implement ``_publish``, ``flush`` and ``close``."""

    def __init__(self, *, thing_name: str, schema_version: int = 1) -> None:
        self.thing_name = thing_name
        self.schema_version = schema_version

    # ── Public contract ──────────────────────────────────────────────────────

    def publish_event(self, event: TrafficEvent) -> None:
        self._safe_publish("event", event)

    def publish_telemetry(self, telemetry: EdgeTelemetry) -> None:
        self._safe_publish("telemetry", telemetry)

    def publish_incident(self, incident: IntersectionIncident) -> None:
        self._safe_publish("incident", incident)

    @abstractmethod
    def flush(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> EventPublisher:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ── Implementation hooks ─────────────────────────────────────────────────

    @abstractmethod
    def _publish(self, envelope: CloudEnvelope) -> None: ...

    def _safe_publish(self, kind: EnvelopeKind, model: BaseModel) -> None:
        try:
            envelope = CloudEnvelope.wrap(
                kind, model, thing_name=self.thing_name, schema_version=self.schema_version
            )
            self._publish(envelope)
        except Exception:  # never propagate into the vision loop / API
            logger.exception("Dropped %s message for thing=%s", kind, self.thing_name)


class NullPublisher(EventPublisher):
    """Default when ``cloud.enabled`` is false: accepts everything, sends nothing."""

    def __init__(self, *, thing_name: str = "urban-edge-local", schema_version: int = 1) -> None:
        super().__init__(thing_name=thing_name, schema_version=schema_version)

    def _publish(self, envelope: CloudEnvelope) -> None:
        return None

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


class FilePublisher(EventPublisher):
    """Appends one ``CloudEnvelope`` JSON object per line (JSONL).

    Used for tests and offline demos: ``tail -f`` the file to watch the stream.
    The file is opened lazily on first publish and each line is flushed.
    """

    def __init__(
        self, path: str | Path, *, thing_name: str, schema_version: int = 1
    ) -> None:
        super().__init__(thing_name=thing_name, schema_version=schema_version)
        self.path = Path(path)
        self._lock = threading.Lock()
        self._fh: IO[str] | None = None

    def _publish(self, envelope: CloudEnvelope) -> None:
        with self._lock:
            if self._fh is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._fh = self.path.open("a", encoding="utf-8")
            self._fh.write(envelope.model_dump_json() + "\n")
            self._fh.flush()

    def flush(self) -> None:
        with self._lock:
            if self._fh is not None:
                self._fh.flush()

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                self._fh.close()
                self._fh = None


def build_publisher(
    *,
    enabled: bool,
    publisher: str,
    thing_name: str,
    schema_version: int = 1,
    file_path: str | None = None,
) -> EventPublisher:
    """Construct the publisher named by config. Disabled or ``"null"`` -> NullPublisher."""
    if not enabled or publisher == "null":
        return NullPublisher(thing_name=thing_name, schema_version=schema_version)
    if publisher == "file":
        if not file_path:
            raise ValueError("cloud.publisher='file' requires cloud.file_path")
        return FilePublisher(file_path, thing_name=thing_name, schema_version=schema_version)
    raise ValueError(f"Unknown cloud.publisher: {publisher!r}")
