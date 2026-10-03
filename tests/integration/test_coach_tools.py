"""The coach's tools (_execute_tool) — what each one writes, scoped to the calling user."""
from datetime import date

import pytest

from app.ai_coach import _execute_tool
from app.models import BodyStat, CoachNote, ExerciseEntry, Goal, MealEntry, Measurement
from tests.builders import day, log_weight, make_note, make_period

TODAY = "2026-09-30"


@pytest.fixture(autouse=True)
def frozen(clock):
    clock.at(TODAY + " 09:00")


def run(user, name, **tool_input):
    return _execute_tool(user.id, name, tool_input)


# --- log_body_stat -------------------------------------------------------------------------

def test_body_stat_defaults_to_today(user):
    assert run(user, "log_body_stat", weight_lbs=201.2)["success"]
    stat = BodyStat.query.one()
    assert (stat.date, float(stat.weight_lbs)) == (date(2026, 9, 30), 201.2)


def test_body_stat_updates_the_same_day_instead_of_duplicating(user):
    run(user, "log_body_stat", weight_lbs=201.2)
    run(user, "log_body_stat", body_fat_pct=29.0)
    stat = BodyStat.query.one()
    assert (float(stat.weight_lbs), float(stat.body_fat_pct)) == (201.2, 29.0)


def test_body_stat_needs_a_value(user):
    assert "error" in run(user, "log_body_stat")


def test_body_stat_honors_a_given_date(user):
    run(user, "log_body_stat", weight_lbs=200, date="2026-09-28")
    assert BodyStat.query.one().date == date(2026, 9, 28)


# --- log_measurement -----------------------------------------------------------------------

def test_measurement(user):
    run(user, "log_measurement", metric="waist", value_in=36.5)
    assert float(Measurement.query.one().value_in) == 36.5


def test_measurement_rejects_unknown_metric(user):
    assert "error" in run(user, "log_measurement", metric="neck", value_in=15)


# --- log_meal ------------------------------------------------------------------------------

def test_meal_is_logged_confirmed(user):
    run(user, "log_meal", description="turkey sandwich", meal_type="lunch", calories=450.4, protein_g=32)
    meal = MealEntry.query.one()
    assert (meal.status, meal.calories, meal.meal_type, meal.drinks) == ("confirmed", 450, "lunch", None)


def test_alcohol_defaults_to_one_drink(user):
    run(user, "log_meal", meal_type="alcohol", calories=150, protein_g=0)
    assert MealEntry.query.one().drink_count == 1


def test_alcohol_keeps_a_given_drink_count(user):
    run(user, "log_meal", meal_type="alcohol", calories=300, protein_g=0, drinks=2)
    assert MealEntry.query.one().drink_count == 2


def test_meal_needs_calories_and_protein(user):
    assert "error" in run(user, "log_meal", calories=300)
    assert MealEntry.query.count() == 0


# --- log_exercise --------------------------------------------------------------------------

def test_cardio_fields(user):
    run(user, "log_exercise", activity="Peloton", duration_min=30, calories_burned=250, sets=9)
    e = ExerciseEntry.query.one()
    assert (e.exercise_type, e.duration_min, e.calories_burned, e.sets) == ("cardio", 30, 250, None)


def test_sets_fields(user):
    run(user, "log_exercise", activity="Pushups", exercise_type="sets", sets=3, reps=15, duration_min=5)
    e = ExerciseEntry.query.one()
    assert (e.sets, e.reps, e.weight_lbs, e.duration_min) == (3, 15, None, None)


def test_hang_fields(user):
    run(user, "log_exercise", activity="Dead hang", exercise_type="hang", sets=4, hang_seconds=30, rest_seconds=60)
    e = ExerciseEntry.query.one()
    assert (e.sets, e.hang_seconds, e.rest_seconds) == (4, 30, 60)


def test_exercise_needs_an_activity(user):
    assert "error" in run(user, "log_exercise")


# --- goals and targets ---------------------------------------------------------------------

def test_goal_attaches_to_the_current_period_and_defaults_to_its_end(user):
    p = make_period(user, start=day(-10), end=day(50))
    log_weight(user, day(0), weight=205)
    run(user, "set_goal", goal_type="weight", target_value=195)
    g = Goal.query.one()
    assert (g.period_id, g.target_date, float(g.starting_value)) == (p.id, day(50), 205)


def test_goal_outside_any_period_has_no_period(user):
    make_period(user, start=day(-60), end=day(-20))  # ended
    run(user, "set_goal", goal_type="waist", target_value=34)
    assert Goal.query.one().period_id is None


def test_nutrition_targets_update_the_current_period(user):
    p = make_period(user, start=day(-10))
    run(user, "set_nutrition_targets", daily_calorie_target=1850.6, daily_protein_target_g=160)
    assert (p.daily_calorie_target, float(p.daily_protein_target_g)) == (1851, 160)


def test_nutrition_targets_need_a_period(user):
    assert "error" in run(user, "set_nutrition_targets", daily_calorie_target=1800)


# --- notes ---------------------------------------------------------------------------------

def test_save_note_normalizes_the_key_and_updates_in_place(user):
    run(user, "save_note", key="Alcohol Strategy", content="Max 2")
    run(user, "save_note", key="alcohol_strategy", content="Max 2, three dry days")
    note = CoachNote.query.one()
    assert (note.key, note.content) == ("alcohol_strategy", "Max 2, three dry days")


def test_delete_note(user):
    make_note(user, key="travel")
    assert run(user, "delete_note", key="Travel")["success"]
    assert CoachNote.query.count() == 0


def test_delete_missing_note_is_an_error(user):
    assert "error" in run(user, "delete_note", key="nope")


# --- scoping and errors --------------------------------------------------------------------

def test_unknown_tool(user):
    assert "error" in run(user, "launch_rockets")


def test_writes_are_scoped_to_the_calling_user(user, other_user):
    make_note(other_user, key="travel", content="theirs")
    run(user, "save_note", key="travel", content="mine")
    run(user, "delete_note", key="travel")
    assert CoachNote.query.filter_by(user_id=other_user.id).one().content == "theirs"
