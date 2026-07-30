import pytest

from vision.prompt_parsers import PROMPT_PRESETS, parse_prompt_response, prompt_for_preset


@pytest.mark.parametrize(
    ("preset", "raw", "summary"),
    [
        (
            "vehicle_count",
            "count=2 | vehicle_types=car:1,truck:1,motorcycle:0 | confidence=high",
            "2 vehicles visible",
        ),
        (
            "congestion",
            "status=moderate | reasoning=Queues are forming in two lanes",
            "Congestion is moderate",
        ),
        ("incident", "status=normal", "No incident visible"),
        (
            "wrong_way",
            "status=no | description=No wrong-way movement is visible",
            "No wrong-way movement is visible",
        ),
        (
            "lane_compliance",
            "status=compliant | description=Vehicles are within marked lanes",
            "Vehicles are within marked lanes",
        ),
        (
            "scene_description",
            "Three vehicles wait at a signalized intersection in daylight.",
            "Three vehicles wait at a signalized intersection in daylight.",
        ),
    ],
)
def test_prompt_parser_handles_canonical_response(
    preset: str,
    raw: str,
    summary: str,
) -> None:
    parsed = parse_prompt_response(preset, raw)

    assert parsed.parse_ok is True
    assert parsed.summary == summary


@pytest.mark.parametrize("preset", sorted(PROMPT_PRESETS.keys()))
def test_prompt_parser_handles_malformed_response(preset: str) -> None:
    parsed = parse_prompt_response(preset, "not in the requested shape")

    if preset == "scene_description":
        assert parsed.parse_ok is True
    else:
        assert parsed.parse_ok is False
    assert parsed.raw == "not in the requested shape"


@pytest.mark.parametrize("preset", sorted(PROMPT_PRESETS.keys()))
def test_prompt_parser_handles_empty_response(preset: str) -> None:
    parsed = parse_prompt_response(preset, "")

    assert parsed.parse_ok is False
    assert parsed.summary is None


def test_prompt_for_preset_rejects_unknown_key() -> None:
    with pytest.raises(ValueError, match="Unknown prompt preset"):
        prompt_for_preset("unknown")

