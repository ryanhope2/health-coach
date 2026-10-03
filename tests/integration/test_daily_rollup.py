"""daily_rollup: confirmed meals grouped by *local* day, plus drinks, exercise, and weight."""
from datetime import datetime

from app.progress import daily_rollup, period_weeks
from tests.builders import (SUNDAY, day, log_drink, log_meal, log_weight, log_workout, make_period)


def test_late_evening_meal_lands_on_its_local_day(user):
    log_meal(user, day(2), "21:30", calories=800)  # 01:30 UTC the next day
    r = daily_rollup(user.id, SUNDAY, day(6))
    assert r[day(2)]["calories"] == 800
    assert r[day(3)]["calories"] == 0


def test_meal_late_on_the_last_day_of_the_range_is_included(user):
    # Regression for the bare-date bound gotcha: a DateTime compared to a bare date
    # string in SQLite silently drops anything after midnight on the boundary day.
    log_meal(user, day(6), "23:30", calories=600)
    assert daily_rollup(user.id, SUNDAY, day(6))[day(6)]["calories"] == 600


def test_meals_outside_the_range_are_ignored(user):
    log_meal(user, day(-1), "23:59")
    log_meal(user, day(7), "00:01")
    r = daily_rollup(user.id, SUNDAY, day(6))
    assert not any(d["meals_logged"] for d in r.values())


def test_pending_meals_are_not_counted(user):
    log_meal(user, day(0), status="pending")
    assert daily_rollup(user.id, SUNDAY, day(0))[day(0)]["meals_logged"] is False


def test_drinks_count_toward_calories_and_drink_totals(user):
    log_meal(user, day(0), calories=1500, protein=100)
    log_drink(user, day(0), drinks=2, calories=300)
    log_drink(user, day(0), drinks=None, calories=150)  # unset counts as 1
    d = daily_rollup(user.id, SUNDAY, day(0))[day(0)]
    assert d["calories"] == 1950
    assert d["drinks"] == 3
    assert d["drink_calories"] == 450


def test_exercise_types(user):
    log_workout(user, day(0), "sets", sets=3, reps=10)
    log_workout(user, day(1), "hang", sets=5, hang_seconds=10)
    log_workout(user, day(2), None)  # legacy row
    r = daily_rollup(user.id, SUNDAY, day(2))
    assert [r[day(i)]["exercise"] for i in range(3)] == [{"strength"}, {"strength"}, {"cardio"}]


def test_weight_and_body_fat_by_day(user):
    log_weight(user, day(1), weight=201.4, body_fat=29.5)
    d = daily_rollup(user.id, SUNDAY, day(1))[day(1)]
    assert (d["weight"], d["body_fat"]) == (201.4, 29.5)


def test_only_the_users_own_data(user, other_user):
    log_meal(other_user, day(0), calories=999)
    assert daily_rollup(user.id, SUNDAY, day(0))[day(0)]["calories"] == 0


def test_period_weeks_newest_first_through_as_of(user):
    p = make_period(user, start=day(-10), end=day(30))
    weeks = period_weeks(user.id, p, day(3))
    assert [w["start"] for w in weeks] == [SUNDAY, day(-7), day(-14)]
    assert weeks[0]["in_progress"] is True
