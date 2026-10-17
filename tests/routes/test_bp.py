"""Blood pressure: logging readings (Body page + /bp/), med-change markers, the /bp/ trends
page, and the CSV download."""
import csv
import io
from datetime import date, time

import pytest

from app.models import BloodPressureReading, MedicationChange
from tests.builders import day, local_dt, log_bp, make_med_change
from tests.conftest import soup


@pytest.fixture(autouse=True)
def frozen(clock):
    clock.at("2026-09-30 21:00")  # Wednesday evening — already Thursday in UTC


# --- logging readings ---------------------------------------------------------------------

def test_logs_a_reading_now_by_default(client):
    client.post("/bp/reading", data={"systolic": "128", "diastolic": "82", "pulse": "64"})
    r = BloodPressureReading.query.one()
    assert (r.systolic, r.diastolic, r.pulse) == (128, 82, 64)
    assert r.taken_at == local_dt(day(3), "21:00")


def test_logs_a_reading_at_a_given_local_date_and_time(client):
    client.post("/bp/reading", data={"systolic": "131", "diastolic": "84", "date": "2026-09-29", "time": "07:15"})
    assert BloodPressureReading.query.one().taken_at == local_dt(day(2), "07:15")


def test_dictated_reading_in_the_first_field_fills_all_three(client):
    client.post("/bp/reading", data={"systolic": "128 over 82 pulse 64", "diastolic": "", "pulse": ""})
    r = BloodPressureReading.query.one()
    assert (r.systolic, r.diastolic, r.pulse) == (128, 82, 64)


@pytest.mark.parametrize("data", [
    {"systolic": "", "diastolic": ""},
    {"systolic": "128", "diastolic": ""},
    {"systolic": "82", "diastolic": "128"},
    {"systolic": "hello", "diastolic": "82"},
])
def test_rejects_incomplete_or_implausible_readings(client, data):
    client.post("/bp/reading", data=data)
    assert BloodPressureReading.query.count() == 0


@pytest.mark.parametrize("next_url, location", [
    ("/body/", "/body/"), (None, "/bp/"), ("//evil.example", "/bp/"),
])
def test_reading_redirect_target_is_allowlisted(client, next_url, location):
    data = {"systolic": "128", "diastolic": "82"} | ({"next": next_url} if next_url else {})
    assert client.post("/bp/reading", data=data).headers["Location"] == location


def test_deletes_a_reading(client, user):
    r = log_bp(user, day(3))
    client.post(f"/bp/reading/{r.id}/delete")
    assert BloodPressureReading.query.count() == 0


def test_body_page_has_the_reading_form_and_recent_readings(client, user):
    log_bp(user, day(3), "07:05", 133, 86, pulse=61)
    page = soup(client.get("/body/"))
    form = page.find("form", action="/bp/reading")
    assert form.find("input", {"name": "next"})["value"] == "/body/"
    assert "133/86" in page.find(id="bpRecent").get_text()
    assert page.find("a", href="/bp/")


# --- trends page --------------------------------------------------------------------------

def test_trends_page_with_no_readings(client):
    r = client.get("/bp/")
    assert r.status_code == 200
    assert soup(r).find(id="bpEmpty")


def test_baseline_progress_before_any_med_change(client, user):
    for i in (1, 2):
        log_bp(user, day(i), "07:00", 140, 90)
        log_bp(user, day(i), "21:00", 130, 84)
    log_bp(user, day(3), "07:00", 138, 88)
    text = soup(client.get("/bp/")).find(id="baseline").get_text(" ", strip=True)
    assert "2 of 7" in text
    assert "136/87" in text  # (140+130+140+130+138)/5, (90+84+90+84+88)/5


def test_compares_each_regimen_to_the_one_before(client, user):
    for i in range(0, 3):
        log_bp(user, day(i), "07:00", 140, 90)
    make_med_change(user, day(3), "Amlodipine 5 → 10 mg")
    log_bp(user, day(3), "07:00", 160, 99)
    log_bp(user, day(3), "21:00", 160, 99)
    rows = soup(client.get("/bp/?settle=0")).select("#regimens .regimen")
    assert [x.find(class_="regimen-label").get_text(strip=True) for x in rows] == ["Amlodipine 5 → 10 mg", "Baseline"]
    assert "+20/+9" in rows[0].get_text()


def test_settle_days_leave_early_readings_out_of_the_comparison(client, user):
    log_bp(user, day(-3), "07:00", 140, 90)
    make_med_change(user, day(-2))
    log_bp(user, day(-1), "07:00", 170, 100)    # within 2 days of the change
    log_bp(user, day(1), "07:00", 130, 84)
    newest = soup(client.get("/bp/?settle=2")).select("#regimens .regimen")[0]
    assert "130/84" in newest.get_text()
    assert "−10/−6" in newest.get_text()


def test_med_change_marks_its_week(client, user):
    log_bp(user, day(1))
    make_med_change(user, day(2), "Losartan added")
    week = soup(client.get("/bp/")).select("#bpWeeks details.week")[0]
    assert "Losartan added" in week.get_text()


# --- med changes --------------------------------------------------------------------------

def test_logs_a_dated_med_change_with_optional_time_and_notes(client):
    client.post("/bp/med-change", data={"date": "2026-09-29", "time": "20:00",
                                        "description": "Amlodipine 5 → 10 mg", "notes": "Per cardiologist"})
    c = MedicationChange.query.one()
    assert (c.date, c.time, c.description, c.notes) == (date(2026, 9, 29), time(20, 0),
                                                         "Amlodipine 5 → 10 mg", "Per cardiologist")


def test_med_change_time_is_optional(client):
    client.post("/bp/med-change", data={"date": "2026-09-29", "description": "Stopped HCTZ"})
    assert MedicationChange.query.one().time is None


@pytest.mark.parametrize("data", [{"date": "2026-09-29", "description": ""}, {"date": "", "description": "x"}])
def test_med_change_needs_a_date_and_description(client, data):
    client.post("/bp/med-change", data=data)
    assert MedicationChange.query.count() == 0


def test_edits_a_med_change(client, user):
    c = make_med_change(user, day(1), "Amlodipine 5 → 10 mg")
    client.post(f"/bp/med-change/{c.id}/update", data={"date": "2026-09-27", "time": "",
                                                       "description": "Amlodipine 5 → 10 mg", "notes": "evening dose"})
    c = MedicationChange.query.one()
    assert (c.date, c.time, c.notes) == (date(2026, 9, 27), None, "evening dose")


def test_deletes_a_med_change(client, user):
    c = make_med_change(user, day(1))
    client.post(f"/bp/med-change/{c.id}/delete")
    assert MedicationChange.query.count() == 0


# --- CSV ----------------------------------------------------------------------------------

def read_csv(response):
    """(reading rows, med-change rows) — the two sections, each as dicts."""
    text = response.get_data(as_text=True)
    assert text.startswith("\ufeff")  # BOM, so Excel reads the UTF-8 arrow in "5 → 10 mg"
    readings_part, changes_part = text[1:].split("\r\n\r\nMedication changes\r\n")
    return list(csv.DictReader(io.StringIO(readings_part))), list(csv.DictReader(io.StringIO(changes_part)))


def test_csv_is_a_download(client):
    r = client.get("/bp/export.csv")
    assert r.mimetype == "text/csv"
    assert r.headers["Content-Disposition"] == 'attachment; filename="blood-pressure-2026-09-30.csv"'


def test_csv_readings_in_local_time_order_tagged_with_their_regimen(client, user):
    log_bp(user, day(2), "21:30", 129, 83, pulse=66)   # Tuesday 9:30pm Eastern = Wednesday UTC
    log_bp(user, day(1), "07:10", 138, 88, pulse=62, notes="before coffee")
    make_med_change(user, day(2), "Amlodipine 5 → 10 mg", time="20:00", notes="Per Dr. X")
    readings, changes = read_csv(client.get("/bp/export.csv"))
    assert readings == [
        {"date": "2026-09-28", "time": "07:10", "systolic": "138", "diastolic": "88", "pulse": "62",
         "regimen": "Baseline", "notes": "before coffee"},
        {"date": "2026-09-29", "time": "21:30", "systolic": "129", "diastolic": "83", "pulse": "66",
         "regimen": "Amlodipine 5 → 10 mg", "notes": ""},
    ]
    assert changes == [{"date": "2026-09-29", "time": "20:00", "change": "Amlodipine 5 → 10 mg", "notes": "Per Dr. X"}]


def test_csv_only_has_my_readings(client, user, other_user):
    log_bp(user, day(1), systolic=130)
    log_bp(other_user, day(1), systolic=150)
    make_med_change(other_user, day(1), "theirs")
    readings, changes = read_csv(client.get("/bp/export.csv"))
    assert [x["systolic"] for x in readings] == ["130"]
    assert changes == []


def test_csv_range_limits_readings(client, user):
    log_bp(user, day(-40), systolic=150)
    log_bp(user, day(1), systolic=130)
    readings, _ = read_csv(client.get("/bp/export.csv?days=30"))
    assert [x["systolic"] for x in readings] == ["130"]


def test_trends_page_links_to_the_csv_with_its_range(client, user):
    log_bp(user, day(1))
    assert soup(client.get("/bp/?days=30")).find("a", href="/bp/export.csv?days=30")


def test_progress_page_links_to_blood_pressure(client, user):
    assert soup(client.get("/progress/")).find("a", href="/bp/")
