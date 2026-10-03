"""Phase 1 skeleton: publish envelopes to AWS IoT Core over MQTT5 (QoS 1).

Design constraints (handoff §5, Phase 1):

- never block the vision loop: ``_publish`` only enqueues; a background thread
  connects and publishes
- bounded queue with a logged drop policy (drop newest when full)
- retry with exponential backoff, then drop and log
- ``awsiotsdk`` is imported lazily inside the default client factory so the
  edge app (and CI) never needs it; tests inject a fake client factory

Topics: ``urban-edge/{thing_name}/events|telemetry|incidents``.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .publisher import CloudEnvelope, EnvelopeKind, EventPublisher

logger = logging.getLogger(__name__)

QOS_AT_LEAST_ONCE = 1

_TOPIC_SUFFIX: dict[EnvelopeKind, str] = {
    "event": "events",
    "telemetry": "telemetry",
    "incident": "incidents",
}


def topic_for(thing_name: str, kind: EnvelopeKind) -> str:
    return f"urban-edge/{thing_name}/{_TOPIC_SUFFIX[kind]}"


@dataclass(frozen=True)
class IotCoreConfig:
    endpoint: str
    thing_name: str
    cert_path: str
    key_path: str
    ca_path: str | None = None


class MqttClient(Protocol):
    """Minimal blocking client surface the publisher needs. Fakes implement this."""

    def connect(self) -> None: ...

    def publish(self, topic: str, payload: bytes, qos: int) -> None:
        """Publish and block until the broker acknowledges (or raise)."""
        ...

    def disconnect(self) -> None: ...


ClientFactory = Callable[[IotCoreConfig], MqttClient]


def awsiot_client_factory(config: IotCoreConfig, *, timeout_s: float = 10.0) -> MqttClient:
    """Build an MQTT5 client from awsiotsdk. Imported lazily: install the ``cloud`` extra."""
    try:
        from awscrt import mqtt5  # type: ignore[import-not-found]
        from awsiot import mqtt5_client_builder  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "IotCorePublisher requires awsiotsdk: pip install 'urban-edge-vision-analytics[cloud]'"
        ) from exc

    class _Awsiot(MqttClient):
        def __init__(self) -> None:
            self._connected = threading.Event()
            self._client = mqtt5_client_builder.mtls_from_path(
                endpoint=config.endpoint,
                cert_filepath=config.cert_path,
                pri_key_filepath=config.key_path,
                ca_filepath=config.ca_path,
                client_id=config.thing_name,
                on_lifecycle_connection_success=lambda _d: self._connected.set(),
            )

        def connect(self) -> None:
            self._client.start()
            if not self._connected.wait(timeout_s):
                raise TimeoutError(f"MQTT connect to {config.endpoint} timed out")

        def publish(self, topic: str, payload: bytes, qos: int) -> None:
            packet = mqtt5.PublishPacket(topic=topic, payload=payload, qos=mqtt5.QoS(qos))
            self._client.publish(packet).result(timeout_s)

        def disconnect(self) -> None:
            self._client.stop()

    return _Awsiot()


class IotCorePublisher(EventPublisher):
    def __init__(
        self,
        config: IotCoreConfig,
        *,
        schema_version: int = 1,
        client_factory: ClientFactory = awsiot_client_factory,
        queue_size: int = 1000,
        max_retries: int = 5,
        backoff_base_s: float = 0.5,
        backoff_max_s: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(thing_name=config.thing_name, schema_version=schema_version)
        self.config = config
        self._client_factory = client_factory
        self._queue: queue.Queue[CloudEnvelope] = queue.Queue(maxsize=queue_size)
        self._max_retries = max_retries
        self._backoff_base_s = backoff_base_s
        self._backoff_max_s = backoff_max_s
        self._sleep = sleep
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()
        self._client: MqttClient | None = None
        self.dropped_count = 0
        self.published_count = 0

    # ── EventPublisher hooks ─────────────────────────────────────────────────

    def _publish(self, envelope: CloudEnvelope) -> None:
        self._ensure_worker()
        try:
            self._queue.put_nowait(envelope)
        except queue.Full:
            self.dropped_count += 1
            logger.warning(
                "IoT Core queue full (%d); dropped %s message (dropped so far: %d)",
                self._queue.maxsize,
                envelope.kind,
                self.dropped_count,
            )

    def flush(self) -> None:
        """Block until every queued message has been handled by the worker."""
        self.drain()

    def drain(self, timeout_s: float | None = None) -> bool:
        """Like ``flush`` but with a timeout. Returns False on timeout or dead worker."""
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        while not self._queue.empty() or self._queue.unfinished_tasks:
            if deadline is not None and time.monotonic() >= deadline:
                return False
            if self._thread is None or not self._thread.is_alive():
                return False
            time.sleep(0.01)
        return True

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=self._backoff_max_s)
        self._thread = None

    # ── Worker ───────────────────────────────────────────────────────────────

    def _ensure_worker(self) -> None:
        with self._thread_lock:
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(
                    target=self._run, name=f"iot-core-{self.thing_name}", daemon=True
                )
                self._thread.start()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    envelope = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    self._deliver(envelope)
                finally:
                    self._queue.task_done()
        finally:
            self._disconnect()

    def _deliver(self, envelope: CloudEnvelope) -> None:
        topic = topic_for(self.thing_name, envelope.kind)
        payload = envelope.model_dump_json().encode("utf-8")
        for attempt in range(self._max_retries + 1):
            if self._stop.is_set():
                break
            try:
                self._connected_client().publish(topic, payload, QOS_AT_LEAST_ONCE)
                self.published_count += 1
                return
            except Exception as exc:
                self._client = None  # reconnect on next attempt
                if attempt == self._max_retries:
                    break
                delay = min(self._backoff_base_s * (2**attempt), self._backoff_max_s)
                logger.warning(
                    "IoT Core publish to %s failed (attempt %d/%d): %s; retrying in %.1fs",
                    topic, attempt + 1, self._max_retries + 1, exc, delay,
                )
                self._sleep(delay)
        self.dropped_count += 1
        logger.error(
            "IoT Core publish to %s gave up after %d attempts; dropped (dropped so far: %d)",
            topic, self._max_retries + 1, self.dropped_count,
        )

    def _connected_client(self) -> MqttClient:
        if self._client is None:
            client = self._client_factory(self.config)
            client.connect()
            self._client = client
        return self._client

    def _disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                logger.exception("IoT Core disconnect failed")
