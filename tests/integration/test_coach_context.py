"""build_context_summary: the data block the coach sees every turn. Asserts on facts
(dates, numbers, which section something lands in), not on prompt wording."""
import pytest

from app.ai_coach import build_context_summary
from app.extensions import db
from app.models import FoodItem
from tests.builders import (SUNDAY, day, log_drink, log_meal, log_weight, log_workout,
                            make_goal, make_note, make_period, make_recap)


def section(text, heading):
    """The lines under a heading, up to the next blank line."""
    after = text.split(heading, 1)[1]
    return after.split("\n\n", 1)[0]


def test_current_week_on_a_sunday_is_that_sunday_through_saturday(user, clock):
    # The reported bug: asked on a Sunday, the coach used the previous week's window.
    clock.at("2026-09-27 08:00")
    ctx = build_context_summary(user)
    assert "2026-09-27 (Sunday) to 2026-10-03 (Saturday)" in ctx
    assert "day 1 of 7" in ctx


def test_current_time_is_local(user, clock):
    clock.at("2026-09-27 21:15")  # already Monday in UTC
    assert "Sunday, September 27, 2026 at 9:15 PM EDT" in build_context_summary(user)


def test_evening_meal_shows_under_today(user, clock):
    clock.at("2026-09-27 22:00")
    log_meal(user, day(0), "21:00", description="late pasta", calories=900)
    ctx = build_context_summary(user)
    assert "late pasta" in section(ctx, "Today (2026-09-27) meals in detail")


def test_daily_totals_include_drinks(user, clock):
    clock.at("2026-09-28 09:00")
    log_meal(user, day(0), calories=1500, protein=120)
    log_drink(user, day(0), drinks=2, calories=300)
    assert "2026-09-27 (Sunday): 1800 kcal, 120g protein, 2 drink(s)" in build_context_summary(user)


def test_meal_detail_covers_only_the_last_three_days(user, clock):
    clock.at("2026-09-30 09:00")
    log_meal(user, day(0), description="sunday eggs")
    log_meal(user, day(1), description="monday eggs")
    ctx = build_context_summary(user)
    assert "monday eggs" in ctx
    assert "sunday eggs" not in ctx


def test_daily_totals_cover_the_last_fourteen_days(user, clock):
    clock.at("2026-09-30 09:00")
    log_meal(user, day(-11), "12:00", calories=111)   # 9/16 — 14 days back, in
    log_meal(user, day(-12), "21:00", calories=222)   # 9/15 evening — 15 days back, out
    ctx = build_context_summary(user)
    assert "2026-09-16 (Wednesday): 111 kcal" in ctx
    assert "2026-09-15" not in ctx


def test_exercise_is_split_into_this_week_and_prior(user, clock):
    clock.at("2026-09-29 09:00")
    log_workout(user, day(-2), activity="Saturday run")
    log_workout(user, day(1), activity="Monday ride")
    ctx = build_context_summary(user)
    this_week = section(ctx, "Exercise — this week").split("Prior exercise")[0]
    assert "Monday ride" in this_week
    assert "Saturday run" not in this_week
    assert "1 day(s) so far" in ctx


def test_notes_period_goals_and_recap_are_included(user, clock):
    clock.at("2026-09-30 09:00")
    p = make_period(user, start=day(-14), name="Fall 2026", calories=1900, protein=160)
    for i in range(7):
        log_weight(user, day(-14 + i), weight=204)
    make_goal(user, p, target=195)
    make_note(user, key="travel", content="Disney trip")
    make_recap(user, week_start=day(-7), content="Solid week of logging.")
    ctx = build_context_summary(user)
    assert "[travel] Disney trip" in ctx
    assert '"Fall 2026"' in ctx
    assert "weight 204.0 lbs" in ctx  # first-week baseline
    assert "1900 kcal" in ctx
    assert "weight: target 195.0" in ctx
    assert "Solid week of logging." in ctx


def test_new_user_gets_a_nudge_to_start_logging(user, clock):
    clock.at("2026-09-30 09:00")
    assert "No data logged yet" in build_context_summary(user)



def test_no_nudge_once_anything_is_logged(user, clock):
    clock.at("2026-09-30 09:00")
    log_weight(user, day(3), weight=200)
    assert "No data logged yet" not in build_context_summary(user)


def test_only_the_users_own_data(user, other_user, clock):
    clock.at("2026-09-30 09:00")
    make_note(other_user, content="their secret")
    log_meal(other_user, day(3), description="their lunch")
    ctx = build_context_summary(user)
    assert "their secret" not in ctx
    assert "their lunch" not in ctx


# --- today so far (server-computed, so the coach never adds it up itself) --------------------

def test_today_so_far_with_targets_and_whats_left(user, clock):
    clock.at("2026-09-30 21:00")
    make_period(user, start=day(-14), calories=2000, protein=160)
    log_meal(user, day(3), "08:00", calories=350, protein=20)   # logged in the app
    log_meal(user, day(3), "20:30", calories=700, protein=45)   # after UTC midnight
    log_drink(user, day(3), "20:45", drinks=2, calories=300)
    log_meal(user, day(2), "21:00", calories=900, protein=50)   # yesterday: not today
    ctx = build_context_summary(user)
    assert ("Today so far (Wed 09/30): 1350 kcal, 65g protein, 2 drink(s) — "
            "targets 2000 kcal / 160g protein, so 650 kcal and 95g protein left") in ctx


def test_today_so_far_over_target(user, clock):
    clock.at("2026-09-30 21:00")
    make_period(user, start=day(-14), calories=2000, protein=100)
    log_meal(user, day(3), calories=2300, protein=120)
    assert "so 300 kcal over and protein target met" in build_context_summary(user)


def test_today_so_far_with_nothing_logged_and_no_period(user, clock):
    clock.at("2026-09-30 09:00")
    assert "Today so far (Wed 09/30): nothing logged yet" in build_context_summary(user)


# --- meal detail lines -------------------------------------------------------------------

def test_meal_lines_show_local_time(user, clock):
    clock.at("2026-09-30 21:00")
    log_meal(user, day(3), "20:30", meal_type="dinner", description="tacos")
    assert "8:30 PM [Dinner] tacos" in build_context_summary(user)


def test_photo_only_meal_shows_its_food_items(user, clock):
    clock.at("2026-09-30 21:00")
    meal = log_meal(user, day(3), "19:00", meal_type="dinner", description=None)
    db.session.add_all([FoodItem(meal_id=meal.id, name="salmon"), FoodItem(meal_id=meal.id, name="rice")])
    db.session.commit()
    ctx = build_context_summary(user)
    assert "[Dinner] salmon, rice" in ctx
    assert "(no description)" not in ctx


def test_pending_meals_are_listed_but_not_counted(user, clock):
    clock.at("2026-09-30 21:00")
    log_meal(user, day(3), "12:00", calories=500, protein=30)
    log_meal(user, day(3), "18:00", status="pending", description="unconfirmed pizza", calories=900)
    ctx = build_context_summary(user)
    assert "unconfirmed pizza" in section(ctx, "Awaiting review")
    assert "Today so far (Wed 09/30): 500 kcal" in ctx
