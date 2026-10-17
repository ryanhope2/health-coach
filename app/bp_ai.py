"""
Read a blood pressure monitor's display from a photo with Claude Vision.

Only fills in the form: the numbers go back to the page for the user to check and save, the
same as dictation, so a misread is caught before it's stored. The photo isn't kept.
"""
import base64
import json
import logging

import anthropic

from .bp_trends import plausible_reading
from .meal_ai import PARSE_MODEL

logger = logging.getLogger(__name__)

READ_EFFORT = "low"  # reading digits; thinking counts toward max_tokens, so leave room for it

READ_SCHEMA = {
    "type": "object",
    "properties": {
        "readable": {"type": "boolean"},
        "systolic": {"type": "integer"},
        "diastolic": {"type": "integer"},
        "pulse": {"type": "integer"},
    },
    "required": ["readable", "systolic", "diastolic", "pulse"],
    "additionalProperties": False,
}

READ_PROMPT = """This is a photo of a home blood pressure monitor's display. Read the measurement it shows.

- Most monitors show systolic (SYS, top/largest), diastolic (DIA, middle), and pulse (PUL or a \
heart symbol, bottom). Use the labels on the display when they're visible.
- Ignore the date, time, memory/average indicators, battery, and irregular-heartbeat symbols.
- Use 0 for pulse if the display doesn't show one.
- If the display is off, shows an error, is too blurry or glared to read with confidence, or \
isn't a blood pressure monitor, set readable to false and use 0 for the numbers. Never guess \
a digit you can't actually see."""


def read_bp_photo(api_key: str, image: bytes, media_type: str) -> dict:
    """{systolic, diastolic, pulse (None if not shown)} from a photo of the monitor.
    Raises ValueError if it can't be read or the numbers aren't a plausible reading."""
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=PARSE_MODEL,
        max_tokens=8000,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                         "data": base64.standard_b64encode(image).decode("utf-8")}},
            {"type": "text", "text": READ_PROMPT},
        ]}],
        output_config={"effort": READ_EFFORT, "format": {"type": "json_schema", "schema": READ_SCHEMA}},
    )
    if message.stop_reason == "refusal":
        raise ValueError("Couldn't read that photo.")
    raw = next((b.text for b in message.content if b.type == "text"), "")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("read_bp_photo JSON parse failed: %s\nRaw: %s", e, raw)
        raise ValueError("Couldn't read that photo.") from e
    reading = data.get("readable") and plausible_reading(
        data.get("systolic") or 0, data.get("diastolic") or 0, data.get("pulse") or None)
    if not reading:
        raise ValueError("Couldn't make out the numbers — try again closer, without glare, or type them in.")
    return reading
