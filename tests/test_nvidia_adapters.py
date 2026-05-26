import httpx
import pytest

from vision.adapters import NvidiaCosmosAdapter, NvidiaEndpointConfig, NvidiaNimAdapter
from vision.live_pipeline import build_detection_adapter
from vision.schemas import InferenceFrame, VehicleClass


def test_build_detection_adapter_requires_endpoint_for_vss():
    with pytest.raises(ValueError, match="vss adapter requires --detector-endpoint"):
        build_detection_adapter("vss", endpoint=None)


def test_nvidia_adapter_parses_detection_response(monkeypatch):
    frame = InferenceFrame(
        frame_id="frame-1",
        camera_id="cam-1",
        timestamp_ms=1000,
        width=640,
        height=360,
        source_type="rtsp",
    )
    captured = {}

    def fake_post(endpoint, headers, json, timeout):
        captured["endpoint"] = endpoint
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return httpx.Response(
            200,
            request=httpx.Request("POST", endpoint),
            json={
                "detections": [
                    {
                        "track_id": "track-1",
                        "vehicle_class": "car",
                        "bounding_box": {
                            "x": 1,
                            "y": 2,
                            "width": 10,
                            "height": 20,
                            "confidence": 0.91,
                        },
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    adapter = NvidiaNimAdapter(
        NvidiaEndpointConfig(
            endpoint="https://nvidia.example/v1/vision",
            api_key="secret",
            model="cosmos-reason",
        )
    )

    inferred = adapter.infer(frame)

    assert captured["endpoint"] == "https://nvidia.example/v1/vision"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["json"]["provider"] == "nvidia_nim"
    assert captured["json"]["model"] == "cosmos-reason"
    assert inferred.detections[0].vehicle_class == VehicleClass.car
    assert inferred.detections[0].bounding_box.confidence == 0.91
    assert inferred.inference_latency_ms is not None


def test_cosmos_reason2_answer_block_is_parsed(monkeypatch):
    frame = InferenceFrame(
        frame_id="frame-1",
        camera_id="cam-1",
        timestamp_ms=1000,
        width=640,
        height=360,
        source_type="rtsp",
        metadata={"video_url": "rtsp://user:pass@example/stream1"},
        frame_bytes=b"jpeg-bytes",
    )
    captured = {}

    def fake_post(endpoint, headers, json, timeout):
        captured["endpoint"] = endpoint
        captured["json"] = json
        return httpx.Response(
            200,
            request=httpx.Request("POST", endpoint),
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "<think>Traffic scene.</think>"
                                '<answer>{"detections":[{"label":"bus",'
                                '"confidence":0.92,"bbox":[1,2,11,22]}]}</answer>'
                            )
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    adapter = NvidiaCosmosAdapter(
        NvidiaEndpointConfig(
            endpoint="http://127.0.0.1:8000/v1",
            model="nvidia/cosmos-reason2-2b",
        )
    )

    inferred = adapter.infer(frame)

    assert captured["endpoint"] == "http://127.0.0.1:8000/v1/chat/completions"
    assert captured["json"]["model"] == "nvidia/cosmos-reason2-2b"
    assert captured["json"]["messages"][1]["content"][0]["type"] == "image_url"
    assert captured["json"]["messages"][1]["content"][0]["image_url"]["url"].startswith(
        "data:image/jpeg;base64,"
    )
    assert inferred.detections[0].vehicle_class == VehicleClass.bus
    assert inferred.detections[0].bounding_box.width == 10
