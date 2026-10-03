"""Operator-selectable prompt presets for the live detection request.

Every preset asks for the same structured detection JSON (the packs depend on
it); the preset only changes the one-sentence summary focus the model writes.
"""
from __future__ import annotations

PROMPT_PRESETS: dict[str, dict[str, str]] = {
    "traffic_detection": {
        "label": "Traffic detection",
        "focus": "",
        "description": "Detections only, plus a neutral one-line scene summary.",
    },
    "congestion": {
        "label": "Congestion",
        "focus": "whether traffic is clear, moderate or heavy and why",
        "description": "Summary rates congestion.",
    },
    "incident": {
        "label": "Incident watch",
        "focus": "any collision, stalled vehicle, debris or anomaly; say 'normal' if none",
        "description": "Summary flags incidents.",
    },
    "pedestrian_safety": {
        "label": "Pedestrian safety",
        "focus": "pedestrians or cyclists in or near the roadway and any conflict with vehicles",
        "description": "Summary focuses on vulnerable road users.",
    },
    "wrong_way": {
        "label": "Wrong-way",
        "focus": "whether any vehicle moves against the marked traffic direction",
        "description": "Summary flags wrong-way movement.",
    },
    "scene_description": {
        "label": "Scene description",
        "focus": "signage state, weather, lighting and anything an operator should know",
        "description": "Richer narrative summary.",
    },
}

DEFAULT_PROMPT_PRESET = "traffic_detection"


def preset_focus(preset: str) -> str:
    return PROMPT_PRESETS.get(preset, PROMPT_PRESETS[DEFAULT_PROMPT_PRESET])["focus"]


def list_presets() -> list[dict[str, str]]:
    return [{"id": key, **value} for key, value in PROMPT_PRESETS.items()]
