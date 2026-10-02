from __future__ import annotations

import base64
import json
import random
import re
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

import httpx

from .schemas import BoundingBox, InferenceFrame, VehicleClass, VehicleDetection


class DetectionAdapter(ABC):
    @abstractmethod
    def infer(self, frame: InferenceFrame, prompt: str = "") -> InferenceFrame:
        ...


class MockDetectionAdapter(DetectionAdapter):
    """Deterministic mock that produces synthetic detections without any model dependency."""

    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)

    def infer(self, frame: InferenceFrame, prompt: str = "") -> InferenceFrame:
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
            update={
                "detections": detections,
                "inference_latency_ms": latency_ms,
                "metadata": {
                    **frame.metadata,
                    "vlm_response": _mock_vlm_response(prompt, len(detections)),
                    "vlm_model": "mock",
                },
            }
        )


def _mock_vlm_response(prompt: str, vehicle_count: int) -> str:
    lowered = prompt.lower()
    if "count the vehicles" in lowered:
        return (
            f"count={vehicle_count} | "
            f"vehicle_types=car:{vehicle_count},truck:0,motorcycle:0 | "
            "confidence=high"
        )
    if "assess traffic congestion" in lowered:
        status = "moderate" if vehicle_count >= 3 else "clear"
        return (
            f"status={status} | "
            f"reasoning={vehicle_count} vehicles visible in the sampled frame"
        )
    if "incident" in lowered or "collision" in lowered:
        return "status=normal"
    if "against the marked traffic direction" in lowered:
        return "status=no | description=No wrong-way movement is visible"
    if "correct lanes" in lowered:
        return "status=compliant | description=Visible vehicles appear lane compliant"
    return f"Synthetic intersection frame with {vehicle_count} visible vehicles"


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
                confidence=float(item.get("confidence", box.get("confidence", 1.0)) or 0.0),
            ),
            frame_id=frame.frame_id,
            timestamp_ms=frame.timestamp_ms,
            metadata={"provider": "local"},
        ))
    return frame.model_copy(update={"detections": detections, "inference_latency_ms": latency_ms})


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


# ── Unified OpenAI-compatible vision adapter (vLLM / Ollama / NIM) ───────────

DETECTION_LABELS = "car|truck|bus|motorcycle|pedestrian|cyclist|unknown"


def detection_prompt(width: int, height: int, focus: str = "") -> str:
    """Prompt that asks for pixel-space boxes in the image we actually sent."""
    focus_line = f" Also write one short sentence about: {focus}." if focus else ""
    return (
        f"You are analyzing a {width}x{height} traffic camera frame. "
        "List every vehicle, pedestrian and cyclist you can see. "
        "Return ONLY JSON (no markdown) with this exact shape:\n"
        '{"detections":[{"label":"' + DETECTION_LABELS + '",'
        '"confidence":0.0,"bbox":[x1,y1,x2,y2]}],"summary":"one sentence"}\n'
        f"bbox values are pixels in the {width}x{height} image, origin top-left. "
        'If nothing is present return {"detections":[],"summary":"..."}.'
        + focus_line
    )


class OpenAIVisionAdapter(DetectionAdapter):
    """Any server with an OpenAI-compatible ``/v1/chat/completions`` that accepts images.

    Covers vLLM (Cosmos-Reason2, Gemma 4), Ollama's ``/v1`` shim and NVIDIA NIM.
    Errors propagate: the caller decides how to surface an outage. Fabricating
    an empty detection list on failure is exactly what we must not do.
    """

    def __init__(
        self,
        endpoint: str,
        model: str,
        *,
        api_key: str | None = None,
        think: bool = False,
        max_tokens: int = 512,
        timeout_s: float = 60.0,
        provider: str = "openai-compatible",
        temperature: float = 0.1,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.think = think
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.provider = provider
        self.temperature = temperature
        self._client = httpx.Client(timeout=timeout_s)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def build_payload(self, frame: InferenceFrame, prompt: str = "") -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        if frame.frame_bytes:
            b64 = base64.b64encode(frame.frame_bytes).decode("ascii")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
        text = prompt or detection_prompt(frame.width, frame.height)
        if not self.think:
            # Cosmos-Reason2 / Qwen-style models honour this to skip <think> blocks.
            text = text + " /no_think"
        content.append({"type": "text", "text": text})
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if not self.think:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        return payload

    def infer(self, frame: InferenceFrame, prompt: str = "") -> InferenceFrame:
        if not frame.frame_bytes:
            raise ValueError("inference frame has no image bytes")
        start = time.perf_counter()
        resp = self._client.post(
            f"{self.endpoint}/chat/completions",
            headers=self._headers(),
            json=self.build_payload(frame, prompt),
        )
        resp.raise_for_status()
        raw = resp.json()
        latency_ms = (time.perf_counter() - start) * 1000
        text = _extract_assistant_text(raw)
        parsed = _parse_cosmos_response(raw)
        inferred = _normalise_detections(frame, parsed, latency_ms)
        usage = raw.get("usage") or {}
        return inferred.model_copy(
            update={
                "metadata": {
                    **inferred.metadata,
                    "vlm_response": text,
                    "vlm_model": self.model,
                    "vlm_summary": _summary_from_text(text),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                }
            }
        )


def _summary_from_text(text: str) -> str | None:
    candidate = _strip_code_fence(text or "")
    answer_match = re.search(r"<answer>\s*(.*?)\s*</answer>", candidate, flags=re.DOTALL)
    if answer_match:
        candidate = answer_match.group(1)
    json_match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
            summary = parsed.get("summary") if isinstance(parsed, dict) else None
            if isinstance(summary, str) and summary.strip():
                return summary.strip()
        except json.JSONDecodeError:
            pass
    # Fall back to the first prose line outside any JSON/think block.
    prose = re.sub(r"<think>.*?</think>", "", candidate, flags=re.DOTALL)
    prose = re.sub(r"\{.*\}", "", prose, flags=re.DOTALL).strip()
    return prose.splitlines()[0][:240] if prose else None


def normalize_detections_to_unit(frame: InferenceFrame) -> InferenceFrame:
    """Rescale bounding boxes to the 0..1 unit square.

    Models disagree on coordinate conventions: Qwen/Cosmos emit pixels of the
    input image, Gemma emits a 0..1000 grid, and some emit fractions. Decide per
    frame from the largest coordinate seen.
    """
    if not frame.detections:
        return frame
    coords: list[float] = []
    for d in frame.detections:
        bb = d.bounding_box
        coords += [bb.x, bb.y, bb.x + bb.width, bb.y + bb.height]
    peak = max(coords) if coords else 0.0
    w = float(frame.width or 1)
    h = float(frame.height or 1)
    if peak <= 1.0:
        sx = sy = 1.0
    elif peak > max(w, h) * 1.05 and peak <= 1000.0:
        sx = sy = 1 / 1000.0
    else:
        sx, sy = 1 / w, 1 / h
    updated = []
    for d in frame.detections:
        bb = d.bounding_box
        x = min(max(bb.x * sx, 0.0), 1.0)
        y = min(max(bb.y * sy, 0.0), 1.0)
        updated.append(
            d.model_copy(
                update={
                    "bounding_box": BoundingBox(
                        x=x,
                        y=y,
                        width=min(max(bb.width * sx, 0.0), 1.0 - x),
                        height=min(max(bb.height * sy, 0.0), 1.0 - y),
                        confidence=bb.confidence,
                    )
                }
            )
        )
    return frame.model_copy(update={"detections": updated})
