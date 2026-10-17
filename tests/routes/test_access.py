"""Cross-cutting: every page needs a login, and no route lets one user see or change
another user's records (friends get accounts on this app — their data stays private)."""
import pytest

from app.models import BloodPressureReading, BodyStat, CoachNote, ExerciseEntry, Goal, MealEntry, Measurement, MedicationChange, SavedMeal, TrackingPeriod
from tests.builders import (day, log_bp, log_meal, log_measurement, log_weight, log_workout, make_goal,
                            make_med_change, make_note, make_period, make_saved_meal)

PUBLIC = {"login", "static"}


def all_routes(app):
    for rule in app.url_map.iter_rules():
        if rule.endpoint in PUBLIC:
            continue
        url = rule.rule
        for arg in rule.arguments:
            url = url.replace(f"<int:{arg}>", "1")
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            yield method, url


def test_every_route_requires_login(app, anon_client):
    routes = list(all_routes(app))
    assert len(routes) > 30
    for method, url in routes:
        r = anon_client.open(url, method=method)
        assert r.status_code == 302, (method, url)
        assert r.headers["Location"].startswith("/login"), (method, url)


def test_login_and_logout(anon_client, user):
    r = anon_client.post("/login?next=/meals/", data={"username": "me", "password": "pw"})
    assert r.headers["Location"] == "/meals/"
    assert anon_client.get("/").status_code == 200
    anon_client.post("/logout")
    assert anon_client.get("/").status_code == 302


def test_wrong_password(anon_client, user):
    r = anon_client.post("/login", data={"username": "me", "password": "nope"})
    assert "Invalid credentials" in r.get_data(as_text=True)


# --- ownership -----------------------------------------------------------------------------
# Each case: how to make the other user's record, the request to try, and the model whose
# row must survive untouched.

OWNED = [
    ("stat", lambda u: log_weight(u, day(0), weight=200), "POST", "/body/stat/{id}/delete", BodyStat),
    ("measurement", lambda u: log_measurement(u, day(0)), "POST", "/body/measurement/{id}/delete", Measurement),
    ("note", lambda u: make_note(u), "POST", "/coach/notes/{id}/update", CoachNote),
    ("note", lambda u: make_note(u), "POST", "/coach/notes/{id}/delete", CoachNote),
    ("workout", lambda u: log_workout(u, day(0)), "POST", "/exercise/{id}/edit", ExerciseEntry),
    ("workout", lambda u: log_workout(u, day(0)), "POST", "/exercise/{id}/delete", ExerciseEntry),
    ("goal", lambda u: make_goal(u), "POST", "/goals/{id}/achieve", Goal),
    ("goal", lambda u: make_goal(u), "POST", "/goals/{id}/delete", Goal),
    ("period", lambda u: make_period(u), "POST", "/goals/period/{id}", TrackingPeriod),
    ("meal", lambda u: log_meal(u, day(0)), "GET", "/meals/{id}/review", MealEntry),
    ("meal", lambda u: log_meal(u, day(0)), "POST", "/meals/{id}/review", MealEntry),
    ("meal", lambda u: log_meal(u, day(0)), "GET", "/meals/{id}/photo", MealEntry),
    ("meal", lambda u: log_meal(u, day(0)), "POST", "/meals/{id}/re-estimate", MealEntry),
    ("meal", lambda u: log_meal(u, day(0)), "POST", "/meals/{id}/delete", MealEntry),
    ("saved", lambda u: make_saved_meal(u), "POST", "/meals/quick/{id}", SavedMeal),
    ("saved", lambda u: make_saved_meal(u), "POST", "/meals/quick/{id}/delete", SavedMeal),
    ("drink", lambda u: make_saved_meal(u, meal_type="alcohol"), "POST", "/meals/quick-drinks/{id}/update", SavedMeal),
    ("bp", lambda u: log_bp(u, day(0)), "POST", "/bp/reading/{id}/delete", BloodPressureReading),
    ("med", lambda u: make_med_change(u, day(0)), "POST", "/bp/med-change/{id}/update", MedicationChange),
    ("med", lambda u: make_med_change(u, day(0)), "POST", "/bp/med-change/{id}/delete", MedicationChange),
]


@pytest.mark.parametrize("make, method, url, model", [c[1:] for c in OWNED],
                         ids=[f"{c[2]} {c[3]}" for c in OWNED])
def test_cannot_touch_another_users_record(client, other_user, db, make, method, url, model):
    row = make(other_user)
    before = {c.name: getattr(row, c.name) for c in model.__table__.columns}
    data = {"name": "x", "key": "x", "content": "x", "activity": "x", "calories": "1",
            "start_date": "2026-01-01", "end_date": "2026-02-01", "description": "x"}
    r = client.open(url.format(id=row.id), method=method, data=data if method == "POST" else None)
    assert r.status_code == 404
    db.session.expire_all()
    after = db.session.get(model, row.id)
    assert after is not None
    assert {c.name: getattr(after, c.name) for c in model.__table__.columns} == before
    assert MealEntry.query.filter_by(user_id=other_user.id).count() == (1 if model is MealEntry else 0)
