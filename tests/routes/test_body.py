from datetime import date

import pytest

from app.models import BodyStat, Measurement
from tests.builders import day, log_weight


@pytest.fixture(autouse=True)
def frozen(clock):
    clock.at("2026-09-30 21:00")


def test_logs_today_by_default(client):
    client.post("/body/stat", data={"weight_lbs": "201.4", "body_fat_pct": "29.5"})
    s = BodyStat.query.one()
    assert (s.date, float(s.weight_lbs), float(s.body_fat_pct)) == (date(2026, 9, 30), 201.4, 29.5)


def test_same_day_updates_instead_of_duplicating(client, user):
    log_weight(user, day(3), weight=202, body_fat=30)
    client.post("/body/stat", data={"weight_lbs": "201", "date": "2026-09-30"})
    s = BodyStat.query.one()
    assert (float(s.weight_lbs), float(s.body_fat_pct)) == (201, 30)


def test_needs_weight_or_body_fat(client):
    client.post("/body/stat", data={"notes": "forgot"})
    assert BodyStat.query.count() == 0


@pytest.mark.parametrize("next_url, location", [
    ("/", "/"), (None, "/body/"), ("//evil.example", "/body/"),
])
def test_redirect_target_is_allowlisted(client, next_url, location):
    data = {"weight_lbs": "200"} | ({"next": next_url} if next_url else {})
    assert client.post("/body/stat", data=data).headers["Location"] == location


def test_logs_a_measurement(client):
    client.post("/body/measurement", data={"metric": "waist", "value_in": "36.5"})
    m = Measurement.query.one()
    assert (m.metric, float(m.value_in)) == ("waist", 36.5)


@pytest.mark.parametrize("data", [{"metric": "neck", "value_in": "15"}, {"metric": "waist", "value_in": ""}])
def test_rejects_bad_measurements(client, data):
    client.post("/body/measurement", data=data)
    assert Measurement.query.count() == 0
