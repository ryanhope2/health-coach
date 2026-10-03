"""meal_ai's handling of the model's reply (the API call itself is faked)."""
import pytest

from app.meal_ai import _extract_json, parse_meal


def test_extracts_plain_json():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extracts_json_wrapped_in_a_code_fence():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_requires_a_photo_or_description():
    with pytest.raises(ValueError):
        parse_meal("key")


def test_totals_are_coerced_to_float_and_bad_values_become_none(claude):
    claude.replies_text('{"items": [], "total_calories": "450", "total_protein_g": "lots", '
                        '"total_carbs_g": 40, "total_fat_g": null, "drinks": 0}')
    result = parse_meal("key", text_description="a sandwich")
    assert result["total_calories"] == 450.0
    assert result["total_protein_g"] is None
    assert result["total_carbs_g"] == 40.0
    assert result["confidence"] == 0.5


def test_missing_items_becomes_an_empty_list(claude):
    claude.replies_text('{"total_calories": 100}')
    assert parse_meal("key", text_description="x")["items"] == []


def test_unparseable_reply_raises_value_error(claude):
    claude.replies_text("Sorry, I can't tell what that is.")
    with pytest.raises(ValueError):
        parse_meal("key", text_description="x")


def test_description_is_sent_to_the_model(claude):
    claude.replies_text('{"items": []}')
    parse_meal("key", text_description="two eggs and toast")
    assert "two eggs and toast" in claude.prompt_text()
