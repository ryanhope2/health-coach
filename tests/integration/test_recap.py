"""Weekly recap: data handed to the model, the forced save_recap tool call, the one-shot
rewrite when it runs long, and the upsert."""
import pytest

from app.models import WeeklyRecap
from app.recap import MAX_RECAP_WORDS, RECAP_EFFORT, build_recap_data, generate_recap
from tests.builders import (SUNDAY, day, log_drink, log_meal, log_workout, make_chat, make_note,
                            make_period, make_recap, local_dt)


@pytest.fixture
def period(user):
    return make_period(user, start=day(-14), end=day(60), calories=2000)


def words(n):
    return " ".join(["word"] * n)


def test_data_uses_the_progress_page_numbers(user, period, clock):
    clock.at("2026-10-05")
    log_meal(user, day(0), calories=2000, protein=150)
    log_meal(user, day(1), calories=2500, protein=100)
    log_workout(user, day(2), "sets", sets=3, reps=10)
    data, week = build_recap_data(user, period, SUNDAY, day(7))
    assert "calories avg 2250 over 2 logged day(s), 1 of 2 at or under 2100" in data
    assert "exercise 1 day(s) (0 cardio, 1 strength)" in data
    assert week["first"] == SUNDAY


def test_data_names_the_peak_drinking_day(user, period, clock):
    # The model once claimed "no night over 2" for a week with a 4-drink Sunday.
    clock.at("2026-10-05")
    log_drink(user, day(0), drinks=4)
    log_drink(user, day(3), drinks=1)
    data, _ = build_recap_data(user, period, SUNDAY, day(7))
    assert "drinks 5 on 2 day(s)" in data
    assert "most in one day 4 (Sun)" in data


def test_data_includes_context_for_why(user, period, clock):
    clock.at("2026-10-05")
    make_note(user, key="travel", content="Disney all week")
    log_meal(user, day(1), description="churros")
    log_workout(user, day(2), activity="Park walking")
    make_chat(user, content="feet hurt", at=local_dt(day(2), "20:00"))
    make_chat(user, content="last week chat", at=local_dt(day(-2), "20:00"))
    data, _ = build_recap_data(user, period, SUNDAY, day(7))
    for fact in ("[travel] Disney all week", "churros", "Park walking", "feet hurt"):
        assert fact in data
    assert "last week chat" not in data


def test_saves_the_tool_call_output(user, period, claude, clock):
    clock.at("2026-10-05")
    claude.saves_recap("Short verdict. Focus: protein.", "Full recap. Focus: protein.")
    recap = generate_recap("key", user, period, SUNDAY)
    assert (recap.headline, recap.content, recap.covers_through) == (
        "Short verdict. Focus: protein.", "Full recap. Focus: protein.", day(6))
    call = claude.calls[0]
    assert call["model"] == "claude-sonnet-5-5"
    assert "tool_choice" not in call and "tools" not in call  # forced tool use 400s on Sonnet 5.5
    assert call["output_config"]["effort"] == RECAP_EFFORT == "low"
    assert call["output_config"]["format"]["schema"]["required"] == ["headline", "recap"]
    assert call["max_tokens"] >= 4000


def test_a_long_recap_gets_exactly_one_rewrite_request(user, period, claude, clock):
    clock.at("2026-10-05")
    claude.saves_recap("Headline.", words(MAX_RECAP_WORDS + 40))
    claude.saves_recap("Headline.", words(120))
    recap = generate_recap("key", user, period, SUNDAY)
    assert len(recap.content.split()) == 120
    assert len(claude.calls) == 2
    second = claude.calls[1]["messages"]
    assert second[-2]["role"] == "assistant"  # its own draft, passed back unchanged
    assert f"{MAX_RECAP_WORDS + 40} words" in second[-1]["content"]


def test_a_recap_at_the_limit_is_not_rewritten(user, period, claude, clock):
    clock.at("2026-10-05")
    claude.saves_recap("Headline.", words(MAX_RECAP_WORDS))
    generate_recap("key", user, period, SUNDAY)
    assert len(claude.calls) == 1


def test_regenerating_rewrites_the_same_row(user, period, claude, clock):
    clock.at("2026-10-05")
    make_recap(user, week_start=SUNDAY, content="old")
    claude.saves_recap("New.", "new recap")
    generate_recap("key", user, period, SUNDAY)
    assert [r.content for r in WeeklyRecap.query.all()] == ["new recap"]


def test_mid_week_recap_covers_through_today_and_says_so_far(user, period, claude, clock):
    clock.at("2026-09-30")
    claude.saves_recap("So far.", "So far this week.")
    recap = generate_recap("key", user, period, SUNDAY)
    assert recap.covers_through == day(3)
    assert "still in progress" in claude.prompt_text()


def test_a_refusal_raises_and_saves_nothing(user, period, claude, clock):
    clock.at("2026-10-05")
    claude.refuses()
    with pytest.raises(ValueError):
        generate_recap("key", user, period, SUNDAY)
    assert WeeklyRecap.query.count() == 0
