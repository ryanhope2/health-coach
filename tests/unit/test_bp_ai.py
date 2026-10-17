"""bp_ai: reading a blood pressure monitor's display from a photo (the API itself is faked)."""
import pytest

from app.bp_ai import READ_EFFORT, read_bp_photo
from app.meal_ai import PARSE_MODEL

JPEG = b"\xff\xd8\xff fake jpeg"


def test_request_sends_the_image_with_structured_output(claude):
    claude.replies_json({"readable": True, "systolic": 128, "diastolic": 82, "pulse": 64})
    read_bp_photo("key", JPEG, "image/jpeg")
    call = claude.calls[0]
    assert call["model"] == PARSE_MODEL
    assert call["output_config"]["effort"] == READ_EFFORT == "low"
    assert call["output_config"]["format"]["type"] == "json_schema"
    image = call["messages"][0]["content"][0]
    assert (image["type"], image["source"]["media_type"]) == ("image", "image/jpeg")
    assert call["max_tokens"] >= 4000  # thinking counts toward it


def test_reads_the_numbers(claude):
    claude.replies_json({"readable": True, "systolic": 128, "diastolic": 82, "pulse": 64})
    assert read_bp_photo("key", JPEG, "image/jpeg") == {"systolic": 128, "diastolic": 82, "pulse": 64}


def test_pulse_not_shown_is_none(claude):
    claude.replies_json({"readable": True, "systolic": 128, "diastolic": 82, "pulse": 0})
    assert read_bp_photo("key", JPEG, "image/jpeg")["pulse"] is None


@pytest.mark.parametrize("reply", [
    {"readable": False, "systolic": 0, "diastolic": 0, "pulse": 0},
    {"readable": True, "systolic": 82, "diastolic": 128, "pulse": 64},   # swapped / implausible
    {"readable": True, "systolic": 128, "diastolic": 0, "pulse": 64},
])
def test_unreadable_or_implausible_display_is_an_error(claude, reply):
    claude.replies_json(reply)
    with pytest.raises(ValueError):
        read_bp_photo("key", JPEG, "image/jpeg")


def test_refusal_is_an_error(claude):
    claude.refuses()
    with pytest.raises(ValueError):
        read_bp_photo("key", JPEG, "image/jpeg")
