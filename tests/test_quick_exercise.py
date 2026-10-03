"""Dashboard "log a workout" modal: posts to exercise.new and returns to the dashboard."""
from app.models import ExerciseEntry

from .base import AppTestCase


class QuickExerciseTest(AppTestCase):
    def _entries(self):
        with self.app.app_context():
            return ExerciseEntry.query.all()

    def test_dashboard_has_workout_modal_on_the_dots(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="quickExerciseModal"', html)
        self.assertIn('data-bs-target="#quickExerciseModal"', html)

    def test_post_with_dashboard_next_logs_and_returns_to_dashboard(self):
        r = self.client.post("/exercise/new", data={
            "activity": "Peloton", "exercise_type": "cardio",
            "duration_min": "30", "date": "2026-10-03", "next": "/",
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["Location"], "/")
        entries = self._entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].duration_min, 30)

    def test_exercise_page_still_redirects_to_itself(self):
        r = self.client.post("/exercise/new", data={"activity": "Run"})
        self.assertEqual(r.headers["Location"], "/exercise/")

    def test_unknown_next_is_ignored(self):
        r = self.client.post("/exercise/new", data={
            "activity": "Run", "next": "https://evil.example/"})
        self.assertEqual(r.headers["Location"], "/exercise/")


class CardioDefaultsTest(AppTestCase):
    def _assert_defaults(self, path):
        html = self.client.get(path).get_data(as_text=True)
        self.assertRegex(html, r'name="activity"[^>]*value="Peloton"')
        self.assertRegex(html, r'name="duration_min"[^>]*value="20"')

    def test_dashboard_modal_defaults_to_peloton_20_min(self):
        self._assert_defaults("/")

    def test_exercise_page_defaults_to_peloton_20_min(self):
        self._assert_defaults("/exercise/")
