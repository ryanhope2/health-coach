import pytest

from app.models import WeeklyRecap
from tests.builders import SUNDAY, day, log_meal, log_weight, make_goal, make_period, make_recap


def test_renders_without_a_period(client):
    assert client.get("/progress/").status_code == 200


def test_renders_a_period_with_data(client, user, clock):
    clock.at("2026-10-01 09:00")
    p = make_period(user, start=day(-14), end=day(60), name="Fall 2026")
    make_goal(user, p, target=195)
    for i in range(18):
        log_weight(user, day(-14 + i), weight=204 - 0.1 * i)
    log_meal(user, day(1))
    make_recap(user, week_start=day(-7), headline="Last week headline.")
    html = client.get("/progress/").get_data(as_text=True)
    assert "Fall 2026" in html
    assert "Last week headline." in html


def test_recap_button_writes_a_recap(client, user, clock, claude):
    clock.at("2026-10-05 09:00")
    make_period(user, start=day(-14))
    claude.saves_recap("Headline.", "Recap.")
    client.post("/progress/recap", data={"week_start": str(SUNDAY)})
    assert WeeklyRecap.query.one().week_start == SUNDAY


def test_any_day_in_the_week_maps_to_its_sunday(client, user, clock, claude):
    clock.at("2026-10-05 09:00")
    make_period(user, start=day(-14))
    claude.saves_recap("Headline.", "Recap.")
    client.post("/progress/recap", data={"week_start": str(day(3))})
    assert WeeklyRecap.query.one().week_start == SUNDAY


@pytest.mark.parametrize("week_start", ["2026-10-11", "garbage", None])
def test_recap_rejects_future_or_bad_weeks_without_calling_the_model(client, user, clock, week_start):
    clock.at("2026-10-05 09:00")
    make_period(user, start=day(-14))
    client.post("/progress/recap", data={"week_start": week_start} if week_start else {})
    assert WeeklyRecap.query.count() == 0


def test_recap_failure_is_reported_not_raised(client, user, clock, claude):
    clock.at("2026-10-05 09:00")
    make_period(user, start=day(-14))
    claude.fails()
    r = client.post("/progress/recap", data={"week_start": str(SUNDAY)}, follow_redirects=True)
    assert "write the recap" in r.get_data(as_text=True)
