"""Prove the API choke points reach a FilePublisher when cloud publishing is enabled via config."""

import asyncio
import importlib

import pytest
from fastapi.testclient import TestClient

from cloud import CloudEnvelope, FilePublisher, NullPublisher
from events.schemas import IntersectionIncident, TrafficEvent
from telemetry.schemas import EdgeTelemetry

CLOUD_ENV = {
    "URBAN_EDGE_CLOUD_ENABLED": "true",
    "URBAN_EDGE_CLOUD_PUBLISHER": "file",
    "URBAN_EDGE_CLOUD_THING_NAME": "test-thing",
    "URBAN_EDGE_CLOUD_TELEMETRY_INTERVAL_S": "0.01",
}


def _reload_main():
    import api.main as main

    return importlib.reload(main)


@pytest.fixture
def cloud_main(tmp_path, monkeypatch):
    out = tmp_path / "cloud.jsonl"
    for key, value in CLOUD_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("URBAN_EDGE_CLOUD_FILE_PATH", str(out))
    main = _reload_main()
    assert isinstance(main._publisher, FilePublisher)
    yield main, out
    main._publisher.close()
    for key in [*CLOUD_ENV, "URBAN_EDGE_CLOUD_FILE_PATH"]:
        monkeypatch.delenv(key)
    restored = _reload_main()
    assert isinstance(restored._publisher, NullPublisher)


def _envelopes(path):
    return [CloudEnvelope.model_validate_json(line) for line in path.read_text().splitlines()]


def test_default_config_uses_null_publisher():
    import api.main as main

    assert main._settings.cloud.enabled is False
    assert isinstance(main._publisher, NullPublisher)


def test_events_and_incidents_reach_file_publisher(cloud_main):
    main, out = cloud_main
    client = TestClient(main.app)

    event = client.post(
        "/events",
        json={"camera_id": "cam-cloud", "event_type": "wrong_way", "severity": "critical"},
    ).json()
    incident = client.post(
        "/incidents",
        json={"camera_id": "cam-cloud", "event_ids": [event["event_id"]], "severity": "critical"},
    ).json()
    iid = incident["incident_id"]
    assert client.patch(f"/incidents/{iid}", json={"status": "under_review"}).status_code == 200
    transition = client.post(f"/incidents/{iid}/transition", json={"action": "resolve"})
    assert transition.status_code == 200
    # Failed lookups publish nothing.
    assert client.patch("/incidents/nope", json={"status": "resolved"}).status_code == 404

    envelopes = _envelopes(out)
    assert [e.kind for e in envelopes] == ["event", "incident", "incident", "incident"]
    assert all(e.thing_name == "test-thing" for e in envelopes)
    assert TrafficEvent.model_validate(envelopes[0].payload).event_id == event["event_id"]
    statuses = [IntersectionIncident.model_validate(e.payload).status for e in envelopes[1:]]
    assert statuses == ["open", "under_review", "resolved"]


def test_telemetry_snapshot_is_published_from_contract(cloud_main):
    main, out = cloud_main
    main._publish_telemetry()
    (envelope,) = _envelopes(out)
    assert envelope.kind == "telemetry"
    telemetry = EdgeTelemetry.model_validate(envelope.payload)
    assert telemetry.runtime.model_dump(exclude={"schema_version"}) == main._runtime.to_dict()


@pytest.mark.asyncio
async def test_telemetry_loop_publishes_periodically(cloud_main):
    main, out = cloud_main
    task = asyncio.create_task(main._telemetry_loop(0.01))
    try:
        for _ in range(50):
            await asyncio.sleep(0.02)
            if out.exists() and len(out.read_text().splitlines()) >= 2:
                break
    finally:
        task.cancel()
    assert all(e.kind == "telemetry" for e in _envelopes(out))
    assert len(_envelopes(out)) >= 2
