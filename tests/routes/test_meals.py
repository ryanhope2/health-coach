import io
from pathlib import Path

import pytest

from app.models import FoodItem, MealEntry, SavedMeal
from tests.builders import day, log_drink, log_meal, make_saved_meal
from tests.conftest import soup

AJAX = {"X-Requested-With": "XMLHttpRequest"}
PARSED = ('{"items": [{"name": "eggs", "quantity": "2", "calories": 140, "protein_g": 12}], '
          '"total_calories": 340.6, "total_protein_g": 20, "total_carbs_g": 30, "total_fat_g": 12, '
          '"drinks": 0, "confidence": 0.8}')


@pytest.fixture(autouse=True)
def frozen(clock):
    clock.at("2026-09-30 19:00")


# --- /meals/new: AI parse -> pending -> review -----------------------------------------------

def test_new_meal_is_parsed_and_left_pending_for_review(client, claude):
    claude.replies_text(PARSED)
    r = client.post("/meals/new", data={"description": "eggs and toast", "meal_type": "breakfast"},
                    headers=AJAX)
    meal = MealEntry.query.one()
    assert r.get_json() == {"redirect": f"/meals/{meal.id}/review"}
    assert (meal.status, meal.calories, meal.meal_type) == ("pending", 341, "breakfast")
    assert FoodItem.query.one().name == "eggs"


def test_ai_failure_still_lands_on_review(client, claude):
    claude.fails()
    r = client.post("/meals/new", data={"description": "mystery"}, headers=AJAX)
    meal = MealEntry.query.one()
    assert r.get_json() == {"redirect": f"/meals/{meal.id}/review"}
    assert meal.calories is None


def test_needs_a_description_or_photo(client):
    r = client.post("/meals/new", data={"description": " "}, headers=AJAX)
    assert r.status_code == 400
    assert MealEntry.query.count() == 0


def test_rejects_unsupported_photo_types(client):
    r = client.post("/meals/new", data={"photo": (io.BytesIO(b"x"), "meal.exe")},
                    headers=AJAX, content_type="multipart/form-data")
    assert r.status_code == 400


def test_photo_is_saved_under_the_instance_dir_and_sent_to_the_model(client, claude, app):
    claude.replies_text(PARSED)
    client.post("/meals/new", data={"photo": (io.BytesIO(b"\xff\xd8jpeg"), "dinner.jpg")},
                headers=AJAX, content_type="multipart/form-data")
    path = Path(MealEntry.query.one().photo_path)
    assert path.exists() and str(path).startswith(app.instance_path)
    image = claude.calls[0]["messages"][0]["content"][0]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/jpeg"


def test_backdated_meal_lands_on_that_local_day(client, claude):
    claude.replies_text(PARSED)
    client.post("/meals/new", data={"description": "x", "logged_date": "2026-09-28"}, headers=AJAX)
    from app.timeutils import to_local_date
    assert to_local_date(MealEntry.query.one().logged_at) == day(1)


def test_typed_drink_count_beats_the_ai_estimate(client, claude):
    claude.replies_text(PARSED.replace('"drinks": 0', '"drinks": 1'))
    client.post("/meals/new", data={"description": "wine", "meal_type": "alcohol", "drinks": "2"},
                headers=AJAX)
    assert MealEntry.query.one().drink_count == 2


# --- review -------------------------------------------------------------------------------------

def test_review_confirms_with_edits(client, user):
    meal = log_meal(user, day(3), status="pending", meal_type="snack")
    client.post(f"/meals/{meal.id}/review", data={"meal_type": "lunch", "calories": "610",
                                                  "protein_g": "41.5"})
    assert (meal.status, meal.meal_type, meal.calories, float(meal.protein_g)) == (
        "confirmed", "lunch", 610, 41.5)


def test_review_alcohol_without_a_count_is_one_drink(client, user):
    meal = log_meal(user, day(3), status="pending")
    client.post(f"/meals/{meal.id}/review", data={"meal_type": "alcohol", "calories": "150"})
    assert float(meal.drinks) == 1


def test_save_as_quick_meal_upserts_by_name_case_insensitively(client, user):
    make_saved_meal(user, name="Oatmeal bowl", calories=350)
    meal = log_meal(user, day(3), status="pending")
    client.post(f"/meals/{meal.id}/review", data={
        "meal_type": "breakfast", "calories": "380", "save_as_quick_meal": "1",
        "quick_meal_name": "OATMEAL BOWL"})
    assert [(s.name, s.calories) for s in SavedMeal.query.all()] == [("Oatmeal bowl", 380)]


def test_re_estimate_replaces_items(client, user, claude):
    meal = log_meal(user, day(3), status="pending", description="old")
    claude.replies_text(PARSED)
    client.post(f"/meals/{meal.id}/re-estimate", data={"description": "two eggs"}, headers=AJAX)
    assert (meal.description, meal.calories) == ("two eggs", 341)
    assert "two eggs" in claude.prompt_text()


def test_delete_removes_the_photo_file(client, user, app):
    photo = Path(app.instance_path) / "photos" / "meals" / "x.jpg"
    photo.write_bytes(b"x")
    meal = log_meal(user, day(3))
    meal.photo_path = str(photo)
    client.post(f"/meals/{meal.id}/delete")
    assert not photo.exists()
    assert MealEntry.query.count() == 0


# --- the day rollup list ------------------------------------------------------------------------

def meals_page(client, query=""):
    r = client.get("/meals/" + query)
    assert r.status_code == 200
    return soup(r)


def test_groups_by_local_day_then_meal_type_in_fixed_order(client, user):
    log_drink(user, day(3), "18:00")
    log_meal(user, day(3), "21:30", meal_type="dinner")  # after UTC midnight
    log_meal(user, day(3), "08:00", meal_type="breakfast")
    log_meal(user, day(3), "15:00", meal_type=None)
    page = meals_page(client)
    today = page.select("details")
    assert [d.summary.span.get_text() for d in today] == ["Breakfast", "Dinner", "Alcohol", "Other"]
    assert all(d.has_attr("open") for d in today)


def test_past_days_start_collapsed(client, user):
    log_meal(user, day(1))
    assert not meals_page(client).select_one("details").has_attr("open")


def test_pending_meals_are_listed_separately_not_in_totals(client, user):
    log_meal(user, day(-20), status="pending", description="forgotten pizza", calories=999)
    page = meals_page(client)
    assert "forgotten pizza" in page.get_text()
    assert "999" not in page.get_text()


def test_pages_seven_days_at_a_time(client, user):
    for i in range(9):
        log_meal(user, day(3 - i), description=f"meal {i}")
    first = meals_page(client)
    assert len(first.select("strong")) >= 7
    more = first.find("a", string="Show earlier days")
    assert more["href"] == "/meals/?before=2026-09-24"
    second = meals_page(client, "?before=2026-09-24").get_text()
    assert "meal 7" in second and "meal 8" in second and "meal 6" not in second


def test_garbage_before_param_is_ignored(client, user):
    log_meal(user, day(3), description="today's lunch")
    assert "today's lunch" in meals_page(client, "?before=garbage").get_text()


# --- quick meals and drinks ---------------------------------------------------------------------

def test_quick_log_bumps_last_used(client, user):
    sm = make_saved_meal(user)
    client.post(f"/meals/quick/{sm.id}", data={"meal_type": "breakfast"})
    assert sm.last_used_at is not None


def test_meals_page_splits_quick_meals_and_drinks(client, user):
    make_saved_meal(user)
    drink = make_saved_meal(user, name="Manhattan", meal_type="alcohol")
    page = meals_page(client)
    assert page.select_one(".quick-meal-type-select")
    drink_form = page.find("form", action=f"/meals/quick/{drink.id}")
    assert not drink_form.select(".quick-meal-type")


def test_quick_drink_crud(client):
    client.post("/meals/quick-drinks/new", data={"name": "Manhattan", "calories": "190"})
    sm = SavedMeal.query.one()
    assert (sm.meal_type, sm.calories) == ("alcohol", 190)
    client.post(f"/meals/quick-drinks/{sm.id}/update", data={"name": "Rye Manhattan", "calories": "200"})
    assert (sm.name, sm.calories) == ("Rye Manhattan", 200)
    r = client.post(f"/meals/quick/{sm.id}/delete")
    assert r.headers["Location"] == "/meals/quick-drinks"
    assert SavedMeal.query.count() == 0


def test_quick_drink_needs_a_name(client):
    client.post("/meals/quick-drinks/new", data={"name": "", "calories": "100"})
    assert SavedMeal.query.count() == 0
