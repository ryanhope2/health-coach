from datetime import date

import pytest

from app.models import ExerciseEntry
from tests.builders import day, log_workout
from tests.conftest import soup


def test_logs_a_cardio_workout(client):
    client.post("/exercise/new", data={"activity": "Peloton", "exercise_type": "cardio",
                                       "duration_min": "30", "date": "2026-10-03"})
    e = ExerciseEntry.query.one()
    assert (e.activity, e.duration_min, e.date) == ("Peloton", 30, date(2026, 10, 3))


def test_logs_sets(client):
    client.post("/exercise/new", data={"activity": "Pushups", "exercise_type": "sets",
                                       "sets": "3", "reps": "15"})
    e = ExerciseEntry.query.one()
    assert (e.exercise_type, e.sets, e.reps, e.duration_min) == ("sets", 3, 15, None)


@pytest.mark.parametrize("next_url, location", [
    ("/", "/"),
    (None, "/exercise/"),
    ("https://evil.example/", "/exercise/"),  # open-redirect guard
])
def test_redirect_target_is_allowlisted(client, next_url, location):
    data = {"activity": "Run"}
    if next_url:
        data["next"] = next_url
    assert client.post("/exercise/new", data=data).headers["Location"] == location


def test_edit_changes_type_and_fields(client, user):
    e = log_workout(user, day(0))
    client.post(f"/exercise/{e.id}/edit", data={"activity": "Hang", "exercise_type": "hang",
                                                "sets": "4", "hang_seconds": "20", "date": "2026-09-27"})
    e = ExerciseEntry.query.one()
    assert (e.exercise_type, e.sets, e.hang_seconds) == ("hang", 4, 20)


def test_delete(client, user):
    e = log_workout(user, day(0))
    client.post(f"/exercise/{e.id}/delete")
    assert ExerciseEntry.query.count() == 0


@pytest.mark.parametrize("path, form_id", [("/", "quickExerciseForm"), ("/exercise/", "exerciseForm")])
def test_cardio_defaults_to_peloton_20_min(client, path, form_id):
    form = soup(client.get(path)).find(id=form_id)
    assert form.find("input", attrs={"name": "activity"})["value"] == "Peloton"
    assert form.find("input", attrs={"name": "duration_min"})["value"] == "20"
