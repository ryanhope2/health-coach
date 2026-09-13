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
import re
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

PARSE_MODEL = "claude-sonnet-4-5"

SYSTEM_PROMPT = """You are a nutrition estimation assistant inside a personal fitness tracker. \
Given a photo of a meal and/or a text description of what was eaten, identify the individual \
food items and estimate their nutrition. Be a reasonable, practical estimator — use typical \
portion sizes and standard nutrition data when exact amounts aren't given. It's fine to be \
approximate; the user can correct anything before saving."""

PARSE_PROMPT = """Estimate the nutrition for this meal. Return ONLY valid JSON with this exact structure:

{
  "items": [
    {"name": "string", "quantity": "string, e.g. '1 cup' or '2 slices'", "calories": number, "protein_g": number, "carbs_g": number, "fat_g": number}
  ],
  "total_calories": number,
  "total_protein_g": number,
  "total_carbs_g": number,
  "total_fat_g": number,
  "confidence": 0.0-1.0
}

Rules:
- Break the meal into distinct items rather than one lump entry, when there's more than one component
- All numeric fields are estimates in normal units (calories in kcal, macros in grams)
- confidence reflects how certain you are given what was provided (a clear photo + description is high confidence; a vague description is lower)
- Return ONLY the JSON object, no other text

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


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())
    return json.loads(text.strip())


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
        max_tokens=1536,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )

    raw_text = message.content[0].text if message.content else ""
    try:
        result = _extract_json(raw_text)
    except (json.JSONDecodeError, IndexError, AttributeError) as e:
        logger.error("parse_meal JSON parse failed: %s\nRaw: %s", e, raw_text)
        raise ValueError(f"Failed to parse Claude response as JSON: {e}") from e

    if "items" not in result or not isinstance(result["items"], list):
        result["items"] = []
    for field in ("total_calories", "total_protein_g", "total_carbs_g", "total_fat_g"):
        val = result.get(field)
        if val is not None:
            try:
                result[field] = float(val)
            except (TypeError, ValueError):
                result[field] = None
    result.setdefault("confidence", 0.5)
    result["_raw_text"] = raw_text
    return result
