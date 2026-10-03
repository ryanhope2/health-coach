"""Exercise dots: color = slack left to reach the weekly target, not a raw count.

Each case: (today as days after Sunday, days with a workout, target, expected color).
"""
import pytest

from app.progress import exercise_week_status
from tests.builders import day


@pytest.mark.parametrize("today, done, target, color", [
    (0, [0], 4, "green"),           # Sun, 1 done: 6 days left, 3 needed -> 3 spare
    (2, [0], 4, "green"),           # Tue: Tue-Sat 5 left, 3 needed -> exactly 2 spare
    (3, [0], 4, "yellow"),          # Wed: 4 left, 3 needed -> 1 spare
    (4, [0], 4, "red"),             # Thu: 3 left, 3 needed -> 0 spare
    (6, [0, 1, 2], 4, "red"),       # Sat, today not done: 1 left, 1 needed -> 0 spare
    (1, [0, 1], 4, "green"),        # today done doesn't count as a remaining day: 5 left, 2 needed
    (3, [0, 3], 4, "yellow"),       # Wed done: Thu-Sat 3 left, 2 needed -> 1 spare
    (6, [0, 1, 2, 3], 4, "green"),  # target met
    (4, [0], 2, "green"),           # respects the period's target
    (0, [], 4, "green"),            # fresh week: 7 left, 4 needed
])
def test_color(today, done, target, color):
    status = exercise_week_status(day(today), {day(d) for d in done}, target)
    assert status["color"] == color


def test_days_are_sunday_through_saturday_with_done_flags():
    status = exercise_week_status(day(3), {day(1), day(3)}, 4)
    assert [d["date"] for d in status["days"]] == [day(i) for i in range(7)]
    assert [d["done"] for d in status["days"]] == [False, True, False, True, False, False, False]
    assert status["count"] == 2


def test_dates_outside_the_week_are_ignored():
    status = exercise_week_status(day(3), {day(-1), day(7)}, 4)
    assert status["count"] == 0


def test_no_target_defaults_to_four():
    # Thu, 1 done, target 4 -> red; with target 2 it would be green.
    assert exercise_week_status(day(4), {day(0)}, None)["color"] == "red"
