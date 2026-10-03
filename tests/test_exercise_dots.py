"""Dashboard exercise-dot color: slack toward the weekly target, not a raw count.

Run with: .venv/bin/python -m unittest discover -t . -s tests -v
"""
import re
import unittest
from datetime import date, timedelta
from unittest import mock

from app.extensions import db
from app.models import ExerciseEntry, TrackingPeriod

from .base import AppTestCase

SUNDAY = date(2026, 9, 27)  # a Sunday; the week runs 9/27 - 10/3


def day(offset):
    return SUNDAY + timedelta(days=offset)


class ExerciseDotColorTest(AppTestCase):
    def _colors(self, today_offset, done_offsets, target=4):
        """Render the dashboard as of SUNDAY+today_offset and return the set of
        dot-color classes on the exercise dots."""
        with self.app.app_context():
            db.session.add(TrackingPeriod(
                user_id=self.user_id, name="P", start_date=day(-30),
                end_date=day(60), weekly_exercise_days_target=target))
            for off in done_offsets:
                db.session.add(ExerciseEntry(
                    user_id=self.user_id, date=day(off), activity="run",
                    exercise_type="cardio", duration_min=30))
            db.session.commit()
        with mock.patch("app.timeutils.local_today", return_value=day(today_offset)):
            html = self.client.get("/").get_data(as_text=True)
        block = re.search(r'<div class="dots".*?</div>', html, re.S).group(0)
        return set(re.findall(r"dot-(red|yellow|green)", block))

    def test_one_workout_on_sunday_is_green(self):
        # 6 days left, 3 needed -> 3 spare
        self.assertEqual(self._colors(0, [0]), {"green"})

    def test_two_spare_days_is_green(self):
        # Tue, 1 done: Tue-Sat = 5 left, 3 needed -> exactly 2 spare
        self.assertEqual(self._colors(2, [0]), {"green"})

    def test_one_spare_day_is_yellow(self):
        # Wed, 1 done: Wed-Sat = 4 left, 3 needed -> 1 spare
        self.assertEqual(self._colors(3, [0]), {"yellow"})

    def test_must_hit_every_remaining_day_is_red(self):
        # Thu, 1 done: Thu-Sat = 3 left, 3 needed -> 0 spare
        self.assertEqual(self._colors(4, [0]), {"red"})

    def test_late_week_three_done_is_red(self):
        # Sat, 3 done, today not yet: 1 day left, 1 needed -> 0 spare
        self.assertEqual(self._colors(6, [0, 1, 2]), {"red"})

    def test_todays_workout_is_not_counted_as_a_remaining_day(self):
        # Mon, Sun+Mon done (today done): Tue-Sat = 5 left, 2 needed -> 3 spare
        self.assertEqual(self._colors(1, [0, 1]), {"green"})

    def test_today_done_leaves_one_spare_is_yellow(self):
        # Wed, Sun+Wed done: Thu-Sat = 3 left, 2 needed -> 1 spare
        self.assertEqual(self._colors(3, [0, 3]), {"yellow"})

    def test_goal_met_is_green_even_late_in_week(self):
        self.assertEqual(self._colors(6, [0, 1, 2, 3]), {"green"})

    def test_respects_period_target(self):
        # target 2, Thu, 1 done: Thu-Sat = 3 left, 1 needed -> 2 spare
        self.assertEqual(self._colors(4, [0], target=2), {"green"})


if __name__ == "__main__":
    unittest.main()
