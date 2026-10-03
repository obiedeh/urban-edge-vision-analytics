# Edge-to-cloud architecture (AWS)

Jetson edge nodes publish traffic events, incidents and runtime telemetry to
AWS so an operator can see a live fleet dashboard and manage incidents. Raw
video stays on the device. Cloud publishing is optional, config-driven and
off by default: the edge app keeps working with no network and no AWS account.

Status per phase is tracked in the README section "Edge-to-cloud (AWS)".

## Target architecture

```text
Jetson (Orin / Thor)                                   AWS
┌─────────────────────────────────┐                   ┌──────────────────────────────────────────────┐
│ Greengrass v2 nucleus           │   MQTT (TLS,       │ AWS IoT Core                                  │
│  ├─ component: urban-edge app   │   X.509 per device)│  topics:                                      │
│  │   (existing pipeline)        │ ─────────────────▶ │   urban-edge/{thing}/events                   │
│  ├─ component: cloud-publisher  │                    │   urban-edge/{thing}/telemetry                │
│  │   (new, reads app outputs)   │                    │   urban-edge/{thing}/incidents                │
│  └─ stream manager (buffer,     │                    │  rules ──┬─▶ Timestream for InfluxDB (telemetry)
│      store-and-forward)         │                    │          ├─▶ DynamoDB (incidents, lifecycle)  │
└─────────────────────────────────┘                    │          ├─▶ Firehose ─▶ S3 data lake (all)   │
                                                       │          └─▶ SNS (high-severity alerts)       │
                                                       │ Amazon Managed Grafana ◀── InfluxDB, Athena   │
                                                       │ Operator API: existing FastAPI on ECS Fargate │
                                                       │   behind API Gateway + Cognito (Phase 4)      │
                                                       └──────────────────────────────────────────────┘
```

Use **Timestream for InfluxDB**, not Timestream for LiveAnalytics (closed to
new customers).

## Contract

The Pydantic schemas are the contract; cloud payloads are serialized from
them, never hand-built:

| Kind        | Model                             | Produced at                                        |
|-------------|-----------------------------------|----------------------------------------------------|
| `event`     | `events.schemas.TrafficEvent`     | `POST /events` (after `EventStore.add_event`)      |
| `incident`  | `events.schemas.IntersectionIncident` | open / update / transition incident endpoints  |
| `telemetry` | `telemetry.schemas.EdgeTelemetry` | periodic task, every `cloud.telemetry_interval_s`  |

Every contract model carries `schema_version` (currently `1`). Each message
is wrapped in a `cloud.publisher.CloudEnvelope`:

```json
{
  "schema_version": 1,
  "thing_name": "urban-edge-local",
  "sent_at": "2026-09-28T12:00:00Z",
  "kind": "event",
  "payload": { "...": "<model>.model_dump(mode=\"json\")" }
}
```

`InferenceFrame.frame_bytes` is excluded from every dump, so frames never
leak pixel data even if a later phase publishes them.

## Publisher interface (`cloud/`)

`EventPublisher` exposes `publish_event`, `publish_telemetry`,
`publish_incident`, `flush`, `close` and works as a context manager. A failed
publish is logged and dropped; it never raises into the API or the vision
loop.

| `cloud.publisher` | Class              | Use                                              |
|-------------------|--------------------|--------------------------------------------------|
| `null` (default)  | `NullPublisher`    | Accepts everything, sends nothing.               |
| `file`            | `FilePublisher`    | Appends one envelope per line (JSONL). Demos, tests. |
| `iot_core`        | `IotCorePublisher` | MQTT5 to AWS IoT Core, QoS 1 (Phase 1 skeleton). |

`IotCorePublisher` enqueues on a bounded queue (default 1000) and a
background thread connects and publishes, retrying with capped exponential
backoff. When the queue is full the newest message is dropped and logged.
`awsiotsdk` is only imported when the client is first built:
`pip install '.[cloud]'`.

## Configuration

`api/config.py` loads `configs/local.json` (or the file named by
`URBAN_EDGE_CONFIG`) and validates it. The `cloud` section:

```json
"cloud": {
  "enabled": false,
  "publisher": "null",
  "file_path": null,
  "thing_name": "urban-edge-local",
  "schema_version": 1,
  "telemetry_interval_s": 30
}
```

Every key can be overridden with `URBAN_EDGE_CLOUD_<KEY>` (upper-cased), for
example `URBAN_EDGE_CLOUD_ENABLED=true`. The IoT Core publisher additionally
reads `iot_endpoint`, `cert_path`, `key_path`, `ca_path`; set those through
the environment so certificate locations never land in a tracked config.

## How to demo offline (FilePublisher)

No network, no AWS account. Every event and incident the API handles, plus a
telemetry snapshot every two seconds, is appended to a JSONL file.

```bash
export URBAN_EDGE_CLOUD_ENABLED=true
export URBAN_EDGE_CLOUD_PUBLISHER=file
export URBAN_EDGE_CLOUD_FILE_PATH=/tmp/urban-edge-cloud.jsonl
export URBAN_EDGE_CLOUD_THING_NAME=demo-jetson
export URBAN_EDGE_CLOUD_TELEMETRY_INTERVAL_S=2
uvicorn api.main:app --port 8080
```

In a second terminal:

```bash
tail -f /tmp/urban-edge-cloud.jsonl

curl -s -X POST http://127.0.0.1:8080/events -H 'content-type: application/json' \
  -d '{"camera_id":"cam-001","event_type":"red_light_violation","severity":"critical","vehicle_count":1}'
# → {"kind":"event", ...}   then use the event_id below

curl -s -X POST http://127.0.0.1:8080/incidents -H 'content-type: application/json' \
  -d '{"camera_id":"cam-001","event_ids":["<event_id>"],"severity":"critical","summary":"demo"}'
curl -s -X POST http://127.0.0.1:8080/incidents/<incident_id>/transition \
  -H 'content-type: application/json' -d '{"action":"review"}'
# → two {"kind":"incident", ...} lines: status open, then under_review
```

Each line parses back into the contract:

```python
from cloud import CloudEnvelope
from events.schemas import TrafficEvent

for line in open("/tmp/urban-edge-cloud.jsonl"):
    env = CloudEnvelope.model_validate_json(line)
    if env.kind == "event":
        print(TrafficEvent.model_validate(env.payload))
```

The same file is what an IoT rule would receive per message on
`urban-edge/{thing}/{events|telemetry|incidents}`, so it doubles as a fixture
for the Phase 2 routing work.

## Device provisioning (Phase 1, manual test)

`scripts/provision_device.sh <thing-name>` creates an X.509 certificate and
key pair with the AWS CLI, attaches the IoT policy and Thing, and writes the
files to `~/.urban-edge/certs/<thing-name>` (mode 600). It refuses to write
inside a git checkout, and `.gitignore` excludes `*.pem` and `certs/` as a
second guard. The script prints the `URBAN_EDGE_CLOUD_*` exports to run the
edge app against IoT Core.

The IoT policy (CDK `infra/iot_stack.py`, not yet in the repo) must be
scoped to `urban-edge/${iot:Connection.Thing.ThingName}/*`.

## Guardrails

- No credentials in code, configs or git. Device identity lives outside the repo.
- Infrastructure as code only (AWS CDK, Python) once Phase 1+ lands.
- Everything tagged `project=urban-edge`, `owner=obinna`; budget alarm at $25/month;
  `cdk destroy --all` documented before any always-on resource is created.
- Out of scope: raw video upload, automated enforcement, changes to detection
  models or the vision pipeline.
