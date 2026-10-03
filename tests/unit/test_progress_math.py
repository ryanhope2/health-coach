"""Pure period/week math in app/progress.py — no DB. week_summary runs on hand-built
rollups shaped like daily_rollup()'s output."""
from datetime import timedelta

import pytest

from app.models import TrackingPeriod
from app.progress import calorie_cap, period_position, week_start, week_summary
from tests.builders import SUNDAY, day


def period(start=None, end=None, calories=2000, protein=150, exercise_days=4):
    return TrackingPeriod(name="P", start_date=start or day(-14), end_date=end or day(60),
                          daily_calorie_target=calories, daily_protein_target_g=protein,
                          weekly_exercise_days_target=exercise_days)


def rollup(**by_offset):
    """rollup(d0={...}, d3={...}) -> a full Sun-Sat rollup with those days filled in."""
    days = {}
    for i in range(7):
        d = day(i)
        days[d] = {"date": d, "calories": 0, "protein": 0.0, "drinks": 0.0, "drink_calories": 0,
                   "meals_logged": False, "exercise": set(), "weight": None, "body_fat": None}
        days[d].update(by_offset.get(f"d{i}", {}))
    return days


def meals(calories, protein=0):
    return {"meals_logged": True, "calories": calories, "protein": protein}


AFTER_WEEK = day(7)  # as_of for a finished week


# --- week_start / period_position ------------------------------------------------------

@pytest.mark.parametrize("offset", range(7))
def test_week_start_is_the_sunday_on_or_before(offset):
    assert week_start(day(offset)) == SUNDAY


def test_period_position_counts_partial_first_and_last_weeks():
    # Fri 10/2 -> Tue 10/13: weeks of 9/27, 10/4, 10/11 = 3 weeks
    p = period(start=day(5), end=day(16))
    assert period_position(p, day(5)) == {"week": 1, "total_weeks": 3, "days_left": 11, "ended": False}
    assert period_position(p, day(7))["week"] == 2


def test_period_position_before_start_and_after_end_clamp():
    p = period(start=day(7), end=day(20))
    assert period_position(p, day(0))["week"] == 1
    after = period_position(p, day(30))
    assert after["week"] == after["total_weeks"]
    assert after["days_left"] == 0
    assert after["ended"] is True


# --- calorie_cap -----------------------------------------------------------------------

def test_calorie_cap_is_target_plus_five_percent():
    assert calorie_cap(period(calories=2000)) == 2100


def test_calorie_cap_is_none_without_a_target():
    assert calorie_cap(period(calories=None)) is None
    assert calorie_cap(None) is None


# --- week_summary: calories --------------------------------------------------------------

def test_at_the_cap_is_in_range_and_one_over_is_not():
    s = week_summary(rollup(d0=meals(2100), d1=meals(2101)), period(), SUNDAY, AFTER_WEEK)
    assert s["calories_in_range"] == 1


def test_there_is_no_lower_bound_on_calories():
    s = week_summary(rollup(d0=meals(300)), period(), SUNDAY, AFTER_WEEK)
    assert s["calories_in_range"] == 1


def test_days_without_meals_are_left_out_of_the_average():
    s = week_summary(rollup(d0=meals(2000), d1=meals(1000)), period(), SUNDAY, AFTER_WEEK)
    assert s["meal_days"] == 2
    assert s["calories_avg"] == 1500


def test_today_is_left_out_of_calorie_and_protein_averages():
    s = week_summary(rollup(d0=meals(2000, 150), d1=meals(400, 10)), period(), SUNDAY, day(1))
    assert s["meal_days"] == 1
    assert s["calories_avg"] == 2000
    assert s["protein_avg"] == 150


def test_protein_hit_requires_the_full_target():
    s = week_summary(rollup(d0=meals(1800, 150), d1=meals(1800, 149.9)), period(), SUNDAY, AFTER_WEEK)
    assert s["protein_hit"] == 1


# --- week_summary: drinks and exercise ---------------------------------------------------

def test_drinks_and_exercise_count_today():
    r = rollup(d1={"drinks": 2.0, "drink_calories": 300, "exercise": {"cardio"}})
    s = week_summary(r, period(), SUNDAY, day(1))
    assert (s["drinks"], s["drinking_days"], s["drink_calories"]) == (2.0, 1, 300)
    assert s["exercise_days"] == 1


def test_days_after_as_of_are_not_counted():
    r = rollup(d1={"exercise": {"cardio"}}, d5={"exercise": {"cardio"}})
    assert week_summary(r, period(), SUNDAY, day(3))["exercise_days"] == 1


def test_cardio_and_strength_split_counts_a_mixed_day_in_both():
    r = rollup(d0={"exercise": {"cardio"}}, d1={"exercise": {"strength"}},
               d2={"exercise": {"cardio", "strength"}})
    s = week_summary(r, period(), SUNDAY, AFTER_WEEK)
    assert (s["exercise_days"], s["cardio_days"], s["strength_days"]) == (3, 2, 2)


def test_exercise_met_uses_the_period_target():
    r = rollup(d0={"exercise": {"cardio"}}, d1={"exercise": {"cardio"}})
    assert week_summary(r, period(exercise_days=2), SUNDAY, AFTER_WEEK)["exercise_met"] is True
    assert week_summary(r, period(exercise_days=3), SUNDAY, AFTER_WEEK)["exercise_met"] is False


# --- week_summary: clipping to the period ------------------------------------------------

def test_week_is_clipped_to_the_period_start_and_marked_partial():
    p = period(start=day(3))
    s = week_summary(rollup(d1={"exercise": {"cardio"}}, d4={"exercise": {"cardio"}}), p, SUNDAY, AFTER_WEEK)
    assert s["first"] == day(3)
    assert s["partial"] is True
    assert s["exercise_days"] == 1


def test_in_progress_only_while_as_of_is_inside_the_week():
    assert week_summary(rollup(), period(), SUNDAY, day(3))["in_progress"] is True
    assert week_summary(rollup(), period(), SUNDAY, AFTER_WEEK)["in_progress"] is False


def test_weight_average_ignores_days_without_a_reading():
    s = week_summary(rollup(d0={"weight": 200.0}, d2={"weight": 198.0}), period(), SUNDAY, AFTER_WEEK)
    assert s["weight_avg"] == 199.0
