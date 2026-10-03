"""Weight card: first-week baseline, 7-day average, pace measured at the midpoint of the
averaged readings, and the least-squares projection."""
import pytest

from app.progress import period_baseline, weight_progress
from tests.builders import SUNDAY, day, log_weight, make_goal, make_period


@pytest.fixture
def period(user):
    # 70 days, goal 193 from a 200 baseline -> pace -0.1 lb/day
    return make_period(user, start=SUNDAY, end=day(70))


@pytest.fixture
def goal(user, period):
    return make_goal(user, period, target=193)


def first_week_at(user, weight=200.0):
    for i in range(7):
        log_weight(user, day(i), weight=weight)


def test_baseline_is_the_average_of_the_first_seven_days(user, period):
    log_weight(user, day(0), weight=201)
    log_weight(user, day(3), weight=199)
    log_weight(user, day(7), weight=150)  # day 8: outside the window
    assert period_baseline(user.id, period, "weight_lbs") == 200


def test_baseline_is_none_without_first_week_readings(user, period):
    log_weight(user, day(10), weight=200)
    assert period_baseline(user.id, period, "weight_lbs") is None


def test_pace_is_judged_at_the_midpoint_of_the_averaged_readings(user, period, goal):
    first_week_at(user)
    for i in range(7, 14):
        log_weight(user, day(i), weight=199.3)
    wp = weight_progress(user.id, period, goal, day(13))
    # Midpoint of days 7-13 is day 10 -> pace line 199.0, 0.3 behind = on pace.
    # (Judged at today, day 13, it'd be 0.6 behind — the lag bug this guards against.)
    assert wp["on_pace_value"] == pytest.approx(199.0)
    assert wp["status"] == "on pace"
    assert wp["gap"] == pytest.approx(0.3)


@pytest.mark.parametrize("current, status", [(199.6, "behind"), (198.4, "ahead"), (199.5, "on pace")])
def test_pace_status_uses_a_half_pound_tolerance(user, period, goal, current, status):
    first_week_at(user)
    for i in range(7, 14):
        log_weight(user, day(i), weight=current)
    assert weight_progress(user.id, period, goal, day(13))["status"] == status


def test_no_pace_without_a_goal(user, period):
    first_week_at(user)
    wp = weight_progress(user.id, period, None, day(10))
    assert wp["status"] is None
    assert wp["chart"]["pace"] is None


def test_no_projection_before_two_weeks(user, period, goal):
    first_week_at(user)
    assert weight_progress(user.id, period, goal, day(13))["projection"] is None


def test_projection_is_a_least_squares_fit_to_the_period_end(user, period, goal):
    for i in range(21):
        log_weight(user, day(i), weight=200 - 0.1 * i)
    proj = weight_progress(user.id, period, goal, day(20))["projection"]
    assert proj["per_week"] == pytest.approx(-0.7)
    assert proj["end_value"] == pytest.approx(193.0)


def test_current_is_the_last_seven_days_average(user, period, goal):
    log_weight(user, day(5), weight=210)  # older than 7 days at as_of day(13)
    log_weight(user, day(8), weight=200)
    log_weight(user, day(12), weight=198)
    assert weight_progress(user.id, period, goal, day(13))["current"] == 199
