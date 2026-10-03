"""Dashboard: vitals, exercise dots, and the quick-log modals."""
import pytest

from app.models import MealEntry
from tests.builders import (day, log_drink, log_meal, log_weight, log_workout, make_period,
                            make_saved_meal)
from tests.conftest import soup


def dashboard(client):
    r = client.get("/")
    assert r.status_code == 200
    return soup(r)


def test_renders_for_a_brand_new_user(client):
    assert dashboard(client).find(id="chatForm")


# --- today's calories: the timezone agreement check ----------------------------------------

def test_dashboard_meals_page_and_rollup_agree_on_todays_calories(client, user, clock):
    # From the timezone fix: these three must always agree. 9pm Eastern is after UTC
    # midnight, and the 11:30pm-yesterday meal is the same UTC date as today's.
    clock.at("2026-09-30 22:00")
    log_meal(user, day(2), "23:30", calories=1000)  # yesterday, late
    log_meal(user, day(3), "08:00", calories=400)
    log_meal(user, day(3), "21:00", calories=700)
    log_drink(user, day(3), "21:30", calories=150)
    from app.progress import daily_rollup
    assert daily_rollup(user.id, day(3), day(3))[day(3)]["calories"] == 1250
    dash = dashboard(client).select_one(".vitals").get_text(" ", strip=True)
    meals = soup(client.get("/meals/")).get_text(" ", strip=True)
    assert "1250" in dash
    assert "1250" in meals


# --- weight / body fat trend ---------------------------------------------------------------

def test_weight_trend_against_the_period_baseline(client, user, clock):
    clock.at("2026-09-30 09:00")
    make_period(user, start=day(-14))
    for i in range(7):
        log_weight(user, day(-14 + i), weight=204)
    log_weight(user, day(3), weight=201.5)
    vitals = dashboard(client).select_one(".vitals").get_text(" ", strip=True)
    assert "201.5" in vitals
    assert "2.5" in vitals


def test_trends_are_paired_by_field_not_by_row(client, user, clock):
    # Body fat logged most recently without a weight must not blank the weight trend.
    clock.at("2026-09-30 09:00")
    log_weight(user, day(1), weight=203, body_fat=30)
    log_weight(user, day(2), weight=202)
    log_weight(user, day(3), body_fat=29)
    vitals = dashboard(client).select_one(".vitals").get_text(" ", strip=True)
    assert "202" in vitals and "29" in vitals


# --- exercise dots -------------------------------------------------------------------------

def test_dots_show_this_weeks_workouts_and_color(client, user, clock):
    clock.at("2026-10-01 09:00")  # Thursday
    make_period(user, exercise_days=4)
    log_workout(user, day(0))
    log_workout(user, day(-1))  # last Saturday — not this week
    page = dashboard(client)
    dots = page.select(".dots .dot")
    assert len(dots) == 7
    classes = {c for d in dots for c in d.get("class", []) if c.startswith("dot-")}
    assert "dot-red" in classes  # Thu, 1 done, 3 needed with 3 days left


def test_dots_open_the_workout_modal(client):
    page = dashboard(client)
    assert page.find(id="quickExerciseModal")
    assert page.select_one('[data-bs-target="#quickExerciseModal"]')


# --- quick meal modal ----------------------------------------------------------------------

@pytest.fixture
def saved(user):
    return make_saved_meal(user), make_saved_meal(user, name="Vodka martini", meal_type="alcohol")


def test_quick_tab_lists_saved_meals_with_a_meal_type_picker(client, saved):
    oatmeal, _ = saved
    quick = dashboard(client).find(id="quick-tab-pane")
    assert "Oatmeal bowl" in quick.get_text()
    assert "Vodka martini" not in quick.get_text()
    assert quick.find("form", action=f"/meals/quick/{oatmeal.id}")
    assert quick.select_one(".quick-meal-type-select")
    assert quick.select_one('input[name="meal_type"].quick-meal-type')


def test_drinks_tab_has_no_meal_type_field(client, saved):
    # Adding .quick-meal-type to a drink button would re-time-guess it out of "alcohol".
    drinks = dashboard(client).find(id="drinks-tab-pane")
    assert "Vodka martini" in drinks.get_text()
    assert not drinks.select(".quick-meal-type")


def test_quick_meal_logs_with_the_picked_type_and_returns_to_dashboard(client, saved):
    oatmeal, _ = saved
    r = client.post(f"/meals/quick/{oatmeal.id}", data={"meal_type": "snack", "next": "/"})
    assert r.headers["Location"] == "/"
    meal = MealEntry.query.one()
    assert (meal.meal_type, meal.status, meal.calories) == ("snack", "confirmed", 350)


def test_quick_drink_logs_as_alcohol(client, saved):
    _, martini = saved
    client.post(f"/meals/quick/{martini.id}", data={"next": "/"})
    meal = MealEntry.query.one()
    assert (meal.meal_type, meal.drink_count) == ("alcohol", 1)
