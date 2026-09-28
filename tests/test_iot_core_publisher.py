from __future__ import annotations

import importlib.util
import json
import threading
import time
from datetime import UTC, datetime

import pytest

from cloud import CloudEnvelope, build_publisher
from cloud.iot_core import (
    QOS_AT_LEAST_ONCE,
    IotCoreConfig,
    IotCorePublisher,
    awsiot_client_factory,
    topic_for,
)
from events.schemas import EventType, IntersectionIncident, Severity, TrafficEvent
from telemetry.metrics import InferenceMetrics
from telemetry.runtime import RuntimeSnapshot
from telemetry.schemas import EdgeTelemetry

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
CONFIG = IotCoreConfig(
    endpoint="example-ats.iot.us-east-1.amazonaws.com",
    thing_name="jetson-01",
    cert_path="/outside/repo/device.pem.crt",
    key_path="/outside/repo/private.pem.key",
    ca_path="/outside/repo/AmazonRootCA1.pem",
)


class FakeFactory:
    """Builds fake clients; the failure budget is shared across clients because the
    publisher discards its client after every failed attempt."""

    def __init__(self, *, fail_first: int = 0, block: threading.Event | None = None) -> None:
        self.fail_first = fail_first
        self.block = block
        self.attempts = 0
        self.clients: list[FakeMqttClient] = []

    def __call__(self, config: IotCoreConfig) -> FakeMqttClient:
        assert config == CONFIG
        client = FakeMqttClient(self)
        self.clients.append(client)
        return client


class FakeMqttClient:
    def __init__(self, factory: FakeFactory) -> None:
        self.factory = factory
        self.connected = False
        self.disconnected = False
        self.published: list[tuple[str, bytes, int]] = []

    def connect(self) -> None:
        self.connected = True

    def publish(self, topic: str, payload: bytes, qos: int) -> None:
        self.factory.attempts += 1
        if self.factory.block is not None:
            self.factory.block.wait()
        if self.factory.attempts <= self.factory.fail_first:
            raise ConnectionError("broker unavailable")
        self.published.append((topic, payload, qos))

    def disconnect(self) -> None:
        self.disconnected = True


def _event() -> TrafficEvent:
    return TrafficEvent(
        event_id="e1",
        camera_id="cam-1",
        event_type=EventType.wrong_way,
        severity=Severity.critical,
        timestamp=NOW,
    )


def _publisher(factory, **kwargs) -> IotCorePublisher:
    return IotCorePublisher(CONFIG, client_factory=factory, sleep=lambda _s: None, **kwargs)


def test_topic_layout():
    assert topic_for("jetson-01", "event") == "urban-edge/jetson-01/events"
    assert topic_for("jetson-01", "telemetry") == "urban-edge/jetson-01/telemetry"
    assert topic_for("jetson-01", "incident") == "urban-edge/jetson-01/incidents"


def test_publishes_envelopes_to_topics_with_qos1():
    factory = FakeFactory()
    metrics = InferenceMetrics()
    with _publisher(factory) as pub:
        pub.publish_event(_event())
        pub.publish_telemetry(EdgeTelemetry.from_dataclasses(RuntimeSnapshot(), metrics))
        pub.publish_incident(
            IntersectionIncident(
                incident_id="i1",
                camera_id="cam-1",
                event_ids=["e1"],
                severity=Severity.critical,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        assert pub.drain(timeout_s=5)
    (client,) = factory.clients
    assert client.connected and client.disconnected
    topics = [t for t, _, _ in client.published]
    assert topics == [
        "urban-edge/jetson-01/events",
        "urban-edge/jetson-01/telemetry",
        "urban-edge/jetson-01/incidents",
    ]
    assert all(qos == QOS_AT_LEAST_ONCE for _, _, qos in client.published)
    envelope = CloudEnvelope.model_validate_json(client.published[0][1])
    assert envelope.thing_name == "jetson-01"
    assert TrafficEvent.model_validate(envelope.payload) == _event()
    assert json.loads(client.published[1][1])["kind"] == "telemetry"
    assert pub.published_count == 3 and pub.dropped_count == 0


def test_construction_does_not_connect():
    factory = FakeFactory()
    pub = _publisher(factory)
    assert factory.clients == []
    pub.close()
    assert factory.clients == []


def test_publish_never_blocks_caller():
    gate = threading.Event()
    factory = FakeFactory(block=gate)
    pub = _publisher(factory, queue_size=10)
    started = time.monotonic()
    for _ in range(10):
        pub.publish_event(_event())
    assert time.monotonic() - started < 0.5
    gate.set()
    assert pub.drain(timeout_s=5)
    pub.close()
    assert len(factory.clients[0].published) == 10


def test_bounded_queue_drops_newest_and_logs(caplog):
    gate = threading.Event()
    factory = FakeFactory(block=gate)
    pub = _publisher(factory, queue_size=2)
    with caplog.at_level("WARNING", logger="cloud.iot_core"):
        pub.publish_event(_event())
        deadline = time.monotonic() + 2
        while factory.attempts < 1 and time.monotonic() < deadline:
            time.sleep(0.01)  # worker is now blocked inside publish() holding message 1
        for _ in range(5):
            pub.publish_event(_event())
        # two sit in the queue, the remaining three are dropped immediately
    assert pub.dropped_count == 3
    assert "queue full" in caplog.text
    gate.set()
    assert pub.drain(timeout_s=5)
    pub.close()
    assert len(factory.clients[0].published) == 3


def test_retries_with_backoff_then_succeeds(caplog):
    delays: list[float] = []
    factory = FakeFactory(fail_first=2)
    pub = IotCorePublisher(
        CONFIG,
        client_factory=factory,
        sleep=delays.append,
        max_retries=5,
        backoff_base_s=0.5,
        backoff_max_s=30,
    )
    with caplog.at_level("WARNING", logger="cloud.iot_core"):
        pub.publish_event(_event())
        pub.flush()
    pub.close()
    assert delays == [0.5, 1.0]
    # a failed attempt discards the client, so a fresh one is built per retry
    assert len(factory.clients) == 3
    assert sum(len(c.published) for c in factory.clients) == 1
    assert pub.published_count == 1 and pub.dropped_count == 0
    assert "retrying in 0.5s" in caplog.text


def test_gives_up_after_max_retries_and_logs_drop(caplog):
    delays: list[float] = []
    factory = FakeFactory(fail_first=100)
    pub = IotCorePublisher(
        CONFIG, client_factory=factory, sleep=delays.append, max_retries=3, backoff_base_s=1
    )
    with caplog.at_level("ERROR", logger="cloud.iot_core"):
        pub.publish_event(_event())
        assert pub.drain(timeout_s=5)
    pub.close()
    assert delays == [1, 2, 4]
    assert pub.dropped_count == 1 and pub.published_count == 0
    assert "gave up after 4 attempts" in caplog.text


def test_backoff_is_capped():
    delays: list[float] = []
    factory = FakeFactory(fail_first=100)
    pub = IotCorePublisher(
        CONFIG,
        client_factory=factory,
        sleep=delays.append,
        max_retries=6,
        backoff_base_s=1,
        backoff_max_s=5,
    )
    pub.publish_event(_event())
    assert pub.drain(timeout_s=5)
    pub.close()
    assert delays == [1, 2, 4, 5, 5, 5]


def test_connect_failure_is_retried_not_raised():
    class BadFactory(FakeFactory):
        def __call__(self, config):
            raise OSError("no such cert file")

    pub = IotCorePublisher(
        CONFIG, client_factory=BadFactory(), sleep=lambda _s: None, max_retries=1
    )
    pub.publish_event(_event())  # must not raise
    assert pub.drain(timeout_s=5)
    pub.close()
    assert pub.dropped_count == 1


def test_close_is_idempotent_and_drain_after_close_returns_false():
    pub = _publisher(FakeFactory())
    pub.close()
    pub.close()
    pub.publish_event(_event())  # restarts the worker lazily
    assert pub.drain(timeout_s=5)
    pub.close()


def test_drain_returns_false_when_no_worker_is_running():
    pub = _publisher(FakeFactory())
    envelope = CloudEnvelope.wrap("event", _event(), thing_name="jetson-01", schema_version=1)
    pub._queue.put_nowait(envelope)  # queued, but no worker was ever started
    assert pub.drain(timeout_s=0.1) is False


def test_build_publisher_iot_core_requires_endpoint_and_paths():
    with pytest.raises(ValueError):
        build_publisher(enabled=True, publisher="iot_core", thing_name="t")
    pub = build_publisher(
        enabled=True,
        publisher="iot_core",
        thing_name="jetson-01",
        iot_endpoint=CONFIG.endpoint,
        cert_path=CONFIG.cert_path,
        key_path=CONFIG.key_path,
        ca_path=CONFIG.ca_path,
    )
    assert isinstance(pub, IotCorePublisher)
    assert pub.config == CONFIG
    pub.close()


@pytest.mark.skipif(
    importlib.util.find_spec("awsiot") is not None, reason="awsiotsdk installed"
)
def test_default_factory_explains_missing_extra():
    with pytest.raises(ImportError, match=r"\[cloud\]"):
        awsiot_client_factory(CONFIG)
