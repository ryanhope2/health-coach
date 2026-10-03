from app.models import MealEntry, normalize_note_key


def test_drink_count_is_zero_for_non_alcohol():
    assert MealEntry(meal_type="dinner", drinks=2).drink_count == 0


def test_drink_count_defaults_to_one_when_unset():
    assert MealEntry(meal_type="alcohol").drink_count == 1


def test_drink_count_allows_fractions():
    assert MealEntry(meal_type="alcohol", drinks=0.5).drink_count == 0.5


def test_note_keys_normalize_to_slugs():
    assert normalize_note_key("  Alcohol Strategy! ") == "alcohol_strategy"
    assert normalize_note_key("knee--injury (left)") == "knee_injury_left"
    assert normalize_note_key("x" * 80) == "x" * 50
    assert normalize_note_key("!!!") == ""
