from __future__ import annotations

import base64
import json
import random
import re
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from .schemas import BoundingBox, InferenceFrame, VehicleClass, VehicleDetection


class DetectionAdapter(ABC):
    @abstractmethod
    def infer(self, frame: InferenceFrame) -> InferenceFrame:
        ...


class MockDetectionAdapter(DetectionAdapter):
    """Deterministic mock that produces synthetic detections without any model dependency."""

    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)

    def infer(self, frame: InferenceFrame) -> InferenceFrame:
        start = time.perf_counter()
        n = self._rng.randint(0, 4)
        detections = [
            VehicleDetection(
                track_id=str(uuid.uuid4())[:8],
                vehicle_class=self._rng.choice(list(VehicleClass)),
                bounding_box=BoundingBox(
                    x=self._rng.uniform(0, frame.width * 0.8),
                    y=self._rng.uniform(0, frame.height * 0.8),
                    width=self._rng.uniform(30, 150),
                    height=self._rng.uniform(30, 100),
                    confidence=self._rng.uniform(0.5, 0.99),
                ),
                frame_id=frame.frame_id,
                timestamp_ms=frame.timestamp_ms,
            )
            for _ in range(n)
        ]
        latency_ms = (time.perf_counter() - start) * 1000
        return frame.model_copy(
            update={"detections": detections, "inference_latency_ms": latency_ms}
        )


@dataclass(frozen=True)
class NvidiaEndpointConfig:
    endpoint: str
    api_key: str | None = None
    model: str | None = None
    timeout_s: float = 30.0


class NvidiaHttpAdapter(DetectionAdapter):
    """HTTP adapter scaffold for NVIDIA VSS, Cosmos/world-model, NIM, or gateway services.

    The camera ingress path is separate from this adapter. The payload intentionally sends
    frame metadata today; production integrations should replace or extend this method with
    encoded frames, object tracks, clip references, or VSS asset IDs expected by the service.
    """

    provider: str = "nvidia"

    def __init__(self, config: NvidiaEndpointConfig) -> None:
        self.config = config

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _payload(self, frame: InferenceFrame) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.config.model,
            "frame": {
                "frame_id": frame.frame_id,
                "camera_id": frame.camera_id,
                "timestamp_ms": frame.timestamp_ms,
                "width": frame.width,
                "height": frame.height,
                "source_type": frame.source_type,
            },
        }

    def _parse_response(
        self,
        frame: InferenceFrame,
        data: dict[str, Any],
        latency_ms: float,
    ) -> InferenceFrame:
        detections: list[VehicleDetection] = []
        for item in data.get("detections", []):
            label = str(item.get("vehicle_class", item.get("label", "unknown"))).lower()
            vehicle_class = (
                VehicleClass(label)
                if label in VehicleClass._value2member_map_
                else VehicleClass.unknown
            )
            box = item.get("bounding_box", item.get("bbox", {}))
            detections.append(
                VehicleDetection(
                    track_id=str(item.get("track_id", uuid.uuid4().hex[:8])),
                    vehicle_class=vehicle_class,
                    bounding_box=BoundingBox(
                        x=float(box.get("x", 0.0)),
                        y=float(box.get("y", 0.0)),
                        width=float(box.get("width", 0.0)),
                        height=float(box.get("height", 0.0)),
                        confidence=float(item.get("confidence", box.get("confidence", 1.0))),
                    ),
                    frame_id=frame.frame_id,
                    timestamp_ms=frame.timestamp_ms,
                    metadata={"provider": self.provider},
                )
            )
        return frame.model_copy(
            update={"detections": detections, "inference_latency_ms": latency_ms}
        )

    def infer(self, frame: InferenceFrame) -> InferenceFrame:
        start = time.perf_counter()
        response = httpx.post(
            self.config.endpoint,
            headers=self._headers(),
            json=self._payload(frame),
            timeout=self.config.timeout_s,
        )
        response.raise_for_status()
        latency_ms = (time.perf_counter() - start) * 1000
        return self._parse_response(frame, response.json(), latency_ms)


class NvidiaNimAdapter(NvidiaHttpAdapter):
    provider = "nvidia_nim"


class NvidiaVssAdapter(NvidiaHttpAdapter):
    provider = "nvidia_vss"


class NvidiaCosmosAdapter(NvidiaHttpAdapter):
    provider = "nvidia_cosmos_world_model"

    def _media_content(self, frame: InferenceFrame) -> list[dict[str, Any]]:
        if frame.frame_bytes:
            encoded = base64.b64encode(frame.frame_bytes).decode("ascii")
            return [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                }
            ]
        video_url = frame.metadata.get("video_url")
        if video_url:
            return [{"type": "video_url", "video_url": {"url": video_url}}]
        return []

    def _payload(self, frame: InferenceFrame) -> dict[str, Any]:
        content = self._media_content(frame)
        content.append(
            {
                "type": "text",
                "text": (
                    "Analyze this live smart-intersection camera frame or stream for "
                    "urban edge vision analytics. Return only JSON in the <answer> block "
                    "using this schema: "
                    '{"detections":[{"label":"car|truck|motorcycle|bus|pedestrian|'
                    'cyclist|unknown","confidence":0.0,"bbox":[x1,y1,x2,y2],'
                    '"summary":"..."}]}. '
                    "Use normalized pixel coordinates if exact boxes are unavailable. "
                    f"Frame metadata: camera_id={frame.camera_id}, frame_id={frame.frame_id}. "
                    "Answer in this format: <think>short reasoning</think>"
                    "<answer>{your JSON}</answer>."
                ),
            }
        )
        return {
            "model": self.config.model or "nvidia/cosmos-reason2-2b",
            "messages": [
                {
                    "role": "system",
                    "content": "You are NVIDIA Cosmos Reason2 analyzing traffic camera evidence.",
                },
                {"role": "user", "content": content},
            ],
            "temperature": 0.2,
            "top_p": 0.3,
            "max_tokens": 2048,
            "stream": False,
        }

    def infer(self, frame: InferenceFrame) -> InferenceFrame:
        start = time.perf_counter()
        response = httpx.post(
            f"{self.config.endpoint.rstrip('/')}/chat/completions",
            headers=self._headers(),
            json=self._payload(frame),
            timeout=self.config.timeout_s,
        )
        response.raise_for_status()
        latency_ms = (time.perf_counter() - start) * 1000
        parsed = _parse_cosmos_response(response.json())
        return self._parse_response(frame, parsed, latency_ms)


# ── Local vision adapters (Ollama / vLLM) ────────────────────────────────────
#
# Both Ollama and vLLM expose an OpenAI-compatible /v1/chat/completions API.
# No credentials required — they run locally without auth.
#
# Ollama default: http://localhost:11434
# vLLM default:  http://localhost:8000
#
# Vision-capable Ollama models (install with `ollama pull <name>`):
#   moondream  — 1.8B, fastest, good for traffic frames
#   llava      — 7B,   general-purpose vision
#   llava-phi3 — 3.8B, balanced
#   minicpm-v  — 8B,   high accuracy
#
# Vision-capable vLLM models (load with `vllm serve <hf-model-id>`):
#   llava-hf/llava-1.5-7b-hf
#   Qwen/Qwen2-VL-7B-Instruct
#   mistralai/Pixtral-12B  (requires GPU)

_VISION_PROMPT = (
    "You are a traffic camera AI analyzing an intersection frame. "
    "Detect all vehicles and pedestrians visible. "
    "Return ONLY valid JSON (no markdown, no explanation) in this exact schema:\n"
    '{"detections":[{"label":"car|truck|bus|motorcycle|pedestrian|cyclist|unknown",'
    '"confidence":0.85,"bbox":[x1,y1,x2,y2],"summary":"brief description"}]}\n'
    "Use pixel coordinates. If nothing is detected return {\"detections\":[]}."
)


class LocalVisionAdapter(DetectionAdapter):
    """Base adapter for any OpenAI-compatible local vision server (Ollama or vLLM).

    No authentication required — these servers are expected to run locally.
    Subclasses set `provider` and `default_endpoint`.
    """

    provider: str = "local"
    default_endpoint: str = "http://localhost:11434/v1"
    default_model: str = "llava"

    def __init__(self, endpoint: str | None = None, model: str | None = None) -> None:
        self.endpoint = (endpoint or self.default_endpoint).rstrip("/")
        self.model = model or self.default_model
        self._timeout = 60.0  # vision inference can be slow on CPU

    def _build_payload(self, frame: InferenceFrame) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        if frame.frame_bytes:
            b64 = base64.b64encode(frame.frame_bytes).decode("ascii")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
        content.append({"type": "text", "text": _VISION_PROMPT})
        return {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.1,
            "max_tokens": 512,
            "stream": False,
        }

    def infer(self, frame: InferenceFrame) -> InferenceFrame:
        start = time.perf_counter()
        try:
            resp = httpx.post(
                f"{self.endpoint}/chat/completions",
                headers={"Content-Type": "application/json"},
                json=self._build_payload(frame),
                timeout=self._timeout,
            )
            resp.raise_for_status()
            parsed = _parse_cosmos_response(resp.json())
        except Exception:
            parsed = {"detections": []}
        latency_ms = (time.perf_counter() - start) * 1000
        # Re-use the shared response normaliser from NvidiaHttpAdapter
        return _normalise_detections(frame, parsed, latency_ms)


def _normalise_detections(
    frame: InferenceFrame, data: dict[str, Any], latency_ms: float
) -> InferenceFrame:
    """Shared detection normaliser used by both NVIDIA and local adapters."""
    detections: list[VehicleDetection] = []
    for item in data.get("detections", []):
        if not isinstance(item, dict):
            continue
        label = str(item.get("vehicle_class", item.get("label", "unknown"))).lower()
        vehicle_class = (
            VehicleClass(label)
            if label in VehicleClass._value2member_map_
            else VehicleClass.unknown
        )
        box = item.get("bounding_box", item.get("bbox", {}))
        if isinstance(box, list) and len(box) >= 4:
            x1, y1, x2, y2 = box[:4]
            box = {
                "x": float(x1), "y": float(y1),
                "width": max(float(x2) - float(x1), 0.0),
                "height": max(float(y2) - float(y1), 0.0),
                "confidence": float(item.get("confidence", 1.0)),
            }
        if not isinstance(box, dict):
            continue
        detections.append(VehicleDetection(
            track_id=str(uuid.uuid4())[:8],
            vehicle_class=vehicle_class,
            bounding_box=BoundingBox(
                x=float(box.get("x", 0)),
                y=float(box.get("y", 0)),
                width=float(box.get("width", 0)),
                height=float(box.get("height", 0)),
                confidence=float(item.get("confidence", box.get("confidence", 1.0))),
            ),
            frame_id=frame.frame_id,
            timestamp_ms=frame.timestamp_ms,
            metadata={"provider": "local"},
        ))
    return frame.model_copy(update={"detections": detections, "inference_latency_ms": latency_ms})


class OllamaAdapter(LocalVisionAdapter):
    """Ollama local inference adapter.

    Connects to the Ollama server at http://localhost:11434 (no auth required).
    Install a vision model first:  ollama pull moondream
    """
    provider = "ollama"
    default_endpoint = "http://localhost:11434/v1"
    default_model = "moondream"  # smallest/fastest vision model


class VllmAdapter(LocalVisionAdapter):
    """vLLM local inference adapter.

    Connects to a vLLM server (default http://localhost:8000/v1, no auth required).
    Start vLLM:  vllm serve llava-hf/llava-1.5-7b-hf --port 8000
    """
    provider = "vllm"
    default_endpoint = "http://localhost:8000/v1"
    default_model = "llava-hf/llava-1.5-7b-hf"


def _extract_assistant_text(raw: dict[str, Any]) -> str:
    choices = raw.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return str(content)


def _strip_code_fence(text: str) -> str:
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if fence_match:
        return fence_match.group(1)
    return text


def _parse_cosmos_response(raw: dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw.get("detections"), list):
        return raw
    text = _strip_code_fence(_extract_assistant_text(raw))
    answer_match = re.search(r"<answer>\s*(.*?)\s*</answer>", text, flags=re.DOTALL)
    candidate = answer_match.group(1) if answer_match else text
    json_match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
    if not json_match:
        return {"detections": []}
    try:
        parsed = json.loads(json_match.group(0))
    except json.JSONDecodeError:
        return {"detections": []}
    if not isinstance(parsed, dict) or not isinstance(parsed.get("detections", []), list):
        return {"detections": []}
    normalized = []
    for detection in parsed.get("detections", []):
        if not isinstance(detection, dict):
            continue
        item = dict(detection)
        if "bbox" in item and "bounding_box" not in item:
            bbox = item["bbox"]
            if isinstance(bbox, list) and len(bbox) >= 4:
                x1, y1, x2, y2 = bbox[:4]
                item["bounding_box"] = {
                    "x": x1,
                    "y": y1,
                    "width": max(float(x2) - float(x1), 0.0),
                    "height": max(float(y2) - float(y1), 0.0),
                    "confidence": item.get("confidence", 1.0),
                }
        if "vehicle_class" not in item and "label" in item:
            item["vehicle_class"] = item["label"]
        normalized.append(item)
    return {"detections": normalized}
