"""
Claude-based meal nutrition estimation.

Takes an optional photo and/or free-text description of a meal and returns
a structured estimate: individual food items plus calories/protein/carbs/fat,
and a total. Estimates are always a starting point — the user reviews and
edits before confirming, same as vibe-split's receipt review flow.
"""
import base64
import json
import logging
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

PARSE_MODEL = "claude-sonnet-5-5"
PARSE_EFFORT = "low"  # extraction; thinking counts toward max_tokens, so leave room for it

_NUMBER = {"type": "number"}
# Structured output: the API guarantees the reply is JSON matching this schema, so there's
# no code-fence/trailing-comma cleanup to do (the old prompt-only "return JSON" approach).
PARSE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "quantity": {"type": "string"},
                           "calories": _NUMBER, "protein_g": _NUMBER, "carbs_g": _NUMBER, "fat_g": _NUMBER},
            "required": ["name", "quantity", "calories", "protein_g", "carbs_g", "fat_g"],
            "additionalProperties": False,
        }},
        "total_calories": _NUMBER, "total_protein_g": _NUMBER, "total_carbs_g": _NUMBER,
        "total_fat_g": _NUMBER, "drinks": _NUMBER, "confidence": _NUMBER,
    },
    "required": ["items", "total_calories", "total_protein_g", "total_carbs_g", "total_fat_g",
                 "drinks", "confidence"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are a nutrition estimation assistant inside a personal fitness tracker. \
Given a photo of a meal and/or a text description of what was eaten, identify the individual \
food items and estimate their nutrition. Be a reasonable, practical estimator — use typical \
portion sizes and standard nutrition data when exact amounts aren't given. It's fine to be \
approximate; the user can correct anything before saving."""

PARSE_PROMPT = """Estimate the nutrition for this meal.

Rules:
- Break the meal into distinct items rather than one lump entry, when there's more than one component
- quantity is a portion like "1 cup" or "2 slices"
- All numeric fields are estimates in normal units (calories in kcal, macros in grams)
- drinks is how many alcoholic drinks this is, as a person would count them (2 glasses of wine = 2, half a glass = 0.5, one cocktail = 1); 0 if there's no alcohol
- confidence (0.0-1.0) reflects how certain you are given what was provided (a clear photo + description is high confidence; a vague description is lower)

Meal:
"""


def _load_image_b64(image_path: str) -> tuple[str, str]:
    path = Path(image_path)
    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_type_map.get(path.suffix.lower(), "image/jpeg")
    with open(image_path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return data, media_type


def parse_meal(api_key: str, photo_path: str | None = None, text_description: str | None = None) -> dict:
    """
    Estimate nutrition from a photo and/or text description (at least one required).
    Returns a dict with items[], total_calories, total_protein_g, total_carbs_g,
    total_fat_g, confidence. Raises ValueError if Claude's response can't be parsed.
    """
    if not photo_path and not text_description:
        raise ValueError("parse_meal requires a photo_path and/or text_description")

    client = anthropic.Anthropic(api_key=api_key)

    content = []
    if photo_path:
        img_data, media_type = _load_image_b64(photo_path)
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": img_data},
        })

    prompt = PARSE_PROMPT + (text_description or "(see photo)")
    content.append({"type": "text", "text": prompt})

    message = client.messages.create(
        model=PARSE_MODEL,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_config={"effort": PARSE_EFFORT,
                       "format": {"type": "json_schema", "schema": PARSE_SCHEMA}},
    )

    if message.stop_reason == "refusal":
        raise ValueError("The model declined to estimate this meal.")
    # Read by block type: the response usually leads with a thinking block.
    raw_text = next((b.text for b in message.content if b.type == "text"), "")
    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.error("parse_meal JSON parse failed: %s\nRaw: %s", e, raw_text)
        raise ValueError(f"Failed to parse Claude response as JSON: {e}") from e

    for field in ("total_calories", "total_protein_g", "total_carbs_g", "total_fat_g", "drinks"):
        val = result.get(field)
        if val is not None:
            result[field] = float(val)
    result["_raw_text"] = raw_text
    return result
