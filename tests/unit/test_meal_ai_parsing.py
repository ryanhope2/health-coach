"""meal_ai: the request it makes and how it reads the reply (the API itself is faked)."""
import pytest

from app.meal_ai import PARSE_EFFORT, PARSE_MODEL, parse_meal

PARSED = {"items": [{"name": "eggs", "quantity": "2", "calories": 140, "protein_g": 12,
                     "carbs_g": 1, "fat_g": 10}],
          "total_calories": 450, "total_protein_g": 20, "total_carbs_g": 40, "total_fat_g": 12,
          "drinks": 0, "confidence": 0.8}


def test_requires_a_photo_or_description():
    with pytest.raises(ValueError):
        parse_meal("key")


def test_request_uses_structured_output_and_explicit_effort(claude):
    claude.replies_json(PARSED)
    parse_meal("key", text_description="eggs")
    call = claude.calls[0]
    assert call["model"] == PARSE_MODEL == "claude-sonnet-5-5"
    assert call["output_config"]["effort"] == PARSE_EFFORT == "low"
    schema = call["output_config"]["format"]["schema"]
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert set(schema["required"]) >= {"items", "total_calories", "total_protein_g", "drinks"}
    assert schema["additionalProperties"] is False
    assert "tool_choice" not in call
    assert call["max_tokens"] >= 4000  # thinking counts toward it


def test_reads_the_json_after_a_leading_thinking_block(claude):
    claude.replies_json(PARSED)  # the fake leads with a thinking block, as the API does
    result = parse_meal("key", text_description="eggs")
    assert result["total_calories"] == 450.0
    assert result["items"][0]["name"] == "eggs"


def test_totals_are_floats(claude):
    claude.replies_json(PARSED | {"total_protein_g": 20})
    assert parse_meal("key", text_description="x")["total_protein_g"] == 20.0


def test_a_refusal_raises_value_error(claude):
    claude.refuses()
    with pytest.raises(ValueError, match="declined"):
        parse_meal("key", text_description="x")


def test_description_is_sent_to_the_model(claude):
    claude.replies_json(PARSED)
    parse_meal("key", text_description="two eggs and toast")
    assert "two eggs and toast" in claude.prompt_text()
