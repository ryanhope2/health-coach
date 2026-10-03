import pytest

from app.models import Goal, TrackingPeriod
from tests.builders import day, log_weight, make_goal, make_period


@pytest.fixture(autouse=True)
def frozen(clock):
    clock.at("2026-09-30 09:00")


def period_form(**overrides):
    return {"name": "Winter", "start_date": "2026-12-01", "end_date": "2027-02-28",
            "daily_calorie_target": "1900", "daily_protein_target_g": "160",
            "weekly_exercise_days_target": "4"} | overrides


def test_creates_a_period(client):
    client.post("/goals/period/new", data=period_form())
    p = TrackingPeriod.query.one()
    assert (p.name, p.daily_calorie_target, p.weekly_exercise_days_target) == ("Winter", 1900, 4)


@pytest.mark.parametrize("overrides", [
    {"name": ""},
    {"end_date": "2026-11-30"},  # before the start
    {"start_date": "not-a-date"},
])
def test_rejects_invalid_periods(client, overrides):
    client.post("/goals/period/new", data=period_form(**overrides))
    assert TrackingPeriod.query.count() == 0


def test_rejects_overlapping_periods(client, user):
    make_period(user, start=day(-10), end=day(70))  # through 12/6
    r = client.post("/goals/period/new", data=period_form(), follow_redirects=True)
    assert "overlap" in r.get_data(as_text=True)
    assert TrackingPeriod.query.count() == 1


def test_editing_a_period_does_not_conflict_with_itself(client, user):
    p = make_period(user, start=day(-10), end=day(70))
    client.post(f"/goals/period/{p.id}", data=period_form(
        name="Fall", start_date=str(day(-10)), end_date=str(day(80)), daily_calorie_target="1800"))
    assert (p.end_date, p.daily_calorie_target) == (day(80), 1800)


def test_goal_joins_the_current_period_and_defaults_to_its_end(client, user):
    p = make_period(user, start=day(-10), end=day(50))
    log_weight(user, day(2), weight=203)
    client.post("/goals/new", data={"goal_type": "weight", "target_value": "195"})
    g = Goal.query.one()
    assert (g.period_id, g.target_date, float(g.starting_value)) == (p.id, day(50), 203)


@pytest.mark.parametrize("data", [{"goal_type": "iq", "target_value": "200"},
                                  {"goal_type": "weight", "target_value": ""}])
def test_rejects_bad_goals(client, data):
    client.post("/goals/new", data=data)
    assert Goal.query.count() == 0


def test_achieve_marks_inactive(client, user):
    g = make_goal(user)
    client.post(f"/goals/{g.id}/achieve")
    assert g.is_active is False and g.achieved_at is not None


def test_page_shows_period_position(client, user):
    make_period(user, start=day(-10), end=day(50), name="Fall 2026")
    html = client.get("/goals/").get_data(as_text=True)
    assert "Fall 2026" in html
