"""Every plain form that creates or updates a record carries the double-submit guard
(see "Double-Submit Protection" in CLAUDE.md). Renders every page with data so every
form actually appears, then checks each one."""
import pytest

from tests.builders import (day, log_meal, log_measurement, log_weight, log_workout, make_goal,
                            make_note, make_period, make_saved_meal)
from tests.conftest import soup

# Deliberately unguarded, with the reason.
EXEMPT_ACTIONS = {
    "/login": "not a record write",
    "/logout": "not a record write",
    "/coach/clear": "confirm() dialog is its own friction",
}
EXEMPT_SUFFIXES = {
    "/delete": "deletes get a confirm() and repeating one is harmless",
    "/achieve": "idempotent one-tap toggle",
}
# Submitted via fetch with their own busy state (see Meal Logging Flow / AI Coach).
JS_DRIVEN_IDS = {"mealForm", "quickMealForm", "chatForm"}


@pytest.fixture
def pages(client, user, clock):
    clock.at("2026-09-30 09:00")
    p = make_period(user)
    make_goal(user, p)
    make_note(user)
    make_saved_meal(user)
    make_saved_meal(user, name="Martini", meal_type="alcohol")
    log_weight(user, day(0), weight=200)
    log_measurement(user, day(0))
    log_workout(user, day(0))
    pending = log_meal(user, day(3), status="pending")
    urls = ["/", "/body/", "/meals/", "/meals/new", "/meals/quick-drinks", f"/meals/{pending.id}/review",
            "/exercise/", "/goals/", "/coach/", "/coach/notes", "/progress/"]
    responses = {url: client.get(url) for url in urls}
    assert {url: r.status_code for url, r in responses.items()} == {url: 200 for url in urls}
    return {url: soup(r) for url, r in responses.items()}


def test_record_writing_forms_are_guarded(pages):
    unguarded = []
    for url, page in pages.items():
        for form in page.find_all("form"):
            action = form.get("action") or url
            if (form.get("id") in JS_DRIVEN_IDS or action in EXEMPT_ACTIONS
                    or any(action.endswith(s) for s in EXEMPT_SUFFIXES)
                    or (form.get("method") or "get").lower() != "post"):
                continue
            if "guard-double-submit" not in (form.get("class") or []):
                unguarded.append(f"{url}: <form action={action} id={form.get('id')}>")
    assert unguarded == []
