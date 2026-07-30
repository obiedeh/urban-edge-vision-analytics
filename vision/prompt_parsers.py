from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

PROMPT_PRESETS: dict[str, str] = {
    "vehicle_count": (
        "Count the vehicles visible in this image. Respond in this exact format: "
        "count=N | vehicle_types=car:N,truck:N,motorcycle:N | "
        "confidence=low|medium|high"
    ),
    "congestion": (
        "Assess traffic congestion. Respond: status=clear|moderate|heavy | "
        "reasoning=one short sentence"
    ),
    "incident": (
        "Describe any incident, collision, or anomaly visible. If none, respond: "
        "status=normal. Otherwise: status=incident | "
        "type=collision|stalled|debris|other | severity=info|warning|critical | "
        "description=one sentence"
    ),
    "wrong_way": (
        "Is any vehicle moving against the marked traffic direction? Respond: "
        "status=yes|no | description=one short sentence"
    ),
    "lane_compliance": (
        "Are vehicles in correct lanes? Respond: status=compliant|violation | "
        "description=one short sentence"
    ),
    "scene_description": (
        "Describe the intersection scene in one sentence focused on operator-relevant "
        "detail (vehicles, pedestrians, signage state, weather, lighting)."
    ),
}

DEFAULT_PROMPT_PRESET = "vehicle_count"


class ParsedVlmResponse(BaseModel):
    preset: str
    raw: str
    structured: dict[str, Any] = Field(default_factory=dict)
    parse_ok: bool = False
    summary: str | None = None
    reasoning: str | None = None


def prompt_for_preset(preset: str) -> str:
    try:
        return PROMPT_PRESETS[preset]
    except KeyError as exc:
        raise ValueError(f"Unknown prompt preset '{preset}'") from exc


def parse_prompt_response(preset: str, raw: str | None) -> ParsedVlmResponse:
    text = (raw or "").strip()
    parser = _PARSERS.get(preset)
    if parser is None:
        raise ValueError(f"Unknown prompt preset '{preset}'")
    if not text:
        return ParsedVlmResponse(preset=preset, raw=text)
    return parser(text)


def parse_vehicle_count(raw: str) -> ParsedVlmResponse:
    parts = _pipe_parts(raw)
    count = _as_int(parts.get("count"))
    confidence = parts.get("confidence")
    vehicle_types = _parse_vehicle_types(parts.get("vehicle_types", ""))
    ok = count is not None and confidence in {"low", "medium", "high"}
    structured = {
        "count": count,
        "vehicle_types": vehicle_types,
        "confidence": confidence,
    }
    summary = (
        f"{count} vehicles visible"
        if ok and count is not None
        else raw
    )
    reasoning = f"vehicle_types={vehicle_types} | confidence={confidence}" if ok else None
    return ParsedVlmResponse(
        preset="vehicle_count",
        raw=raw,
        structured=structured,
        parse_ok=ok,
        summary=summary,
        reasoning=reasoning,
    )


def parse_congestion(raw: str) -> ParsedVlmResponse:
    parts = _pipe_parts(raw)
    status = parts.get("status")
    reasoning = parts.get("reasoning")
    ok = status in {"clear", "moderate", "heavy"} and bool(reasoning)
    return ParsedVlmResponse(
        preset="congestion",
        raw=raw,
        structured={"status": status, "reasoning": reasoning},
        parse_ok=ok,
        summary=f"Congestion is {status}" if ok else raw,
        reasoning=reasoning if ok else None,
    )


def parse_incident(raw: str) -> ParsedVlmResponse:
    parts = _pipe_parts(raw)
    status = parts.get("status")
    if status == "normal":
        return ParsedVlmResponse(
            preset="incident",
            raw=raw,
            structured={"status": status},
            parse_ok=True,
            summary="No incident visible",
        )
    incident_type = parts.get("type")
    severity = parts.get("severity")
    description = parts.get("description")
    ok = (
        status == "incident"
        and incident_type in {"collision", "stalled", "debris", "other"}
        and severity in {"info", "warning", "critical"}
        and bool(description)
    )
    return ParsedVlmResponse(
        preset="incident",
        raw=raw,
        structured={
            "status": status,
            "type": incident_type,
            "severity": severity,
            "description": description,
        },
        parse_ok=ok,
        summary=description if ok else raw,
        reasoning=f"type={incident_type} | severity={severity}" if ok else None,
    )


def parse_wrong_way(raw: str) -> ParsedVlmResponse:
    parts = _pipe_parts(raw)
    status = parts.get("status")
    description = parts.get("description")
    ok = status in {"yes", "no"} and bool(description)
    return ParsedVlmResponse(
        preset="wrong_way",
        raw=raw,
        structured={"status": status, "description": description},
        parse_ok=ok,
        summary=description if ok else raw,
        reasoning=f"wrong_way={status}" if ok else None,
    )


def parse_lane_compliance(raw: str) -> ParsedVlmResponse:
    parts = _pipe_parts(raw)
    status = parts.get("status")
    description = parts.get("description")
    ok = status in {"compliant", "violation"} and bool(description)
    return ParsedVlmResponse(
        preset="lane_compliance",
        raw=raw,
        structured={"status": status, "description": description},
        parse_ok=ok,
        summary=description if ok else raw,
        reasoning=f"lane_compliance={status}" if ok else None,
    )


def parse_scene_description(raw: str) -> ParsedVlmResponse:
    sentence = raw.strip()
    return ParsedVlmResponse(
        preset="scene_description",
        raw=raw,
        structured={"description": sentence},
        parse_ok=bool(sentence),
        summary=sentence or None,
    )


def _pipe_parts(raw: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for chunk in raw.split("|"):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        parts[key.strip().lower()] = value.strip()
    return parts


def _as_int(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"-?\d+", value)
    if not match:
        return None
    return int(match.group(0))


def _parse_vehicle_types(raw: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for chunk in raw.split(","):
        if ":" not in chunk:
            continue
        label, value = chunk.split(":", 1)
        parsed = _as_int(value)
        if parsed is not None:
            counts[label.strip().lower()] = parsed
    return counts


_PARSERS: dict[str, Callable[[str], ParsedVlmResponse]] = {
    "vehicle_count": parse_vehicle_count,
    "congestion": parse_congestion,
    "incident": parse_incident,
    "wrong_way": parse_wrong_way,
    "lane_compliance": parse_lane_compliance,
    "scene_description": parse_scene_description,
}

