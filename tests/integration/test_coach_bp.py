"""The coach's blood pressure side: log_blood_pressure / log_med_change tools and the BP
section of the data block."""
from datetime import date, time

import pytest

from app.ai_coach import TOOLS, _execute_tool, build_context_summary
from app.models import BloodPressureReading, MedicationChange
from tests.builders import day, local_dt, log_bp, make_med_change


@pytest.fixture(autouse=True)
def frozen(clock):
    clock.at("2026-09-30 21:10")  # Wednesday evening Eastern, Thursday in UTC


def run(user, name, **tool_input):
    return _execute_tool(user.id, name, tool_input)


def section(text, heading):
    return text.split(heading, 1)[1].split("\n\n", 1)[0]


def test_tools_are_offered():
    names = {t["name"] for t in TOOLS}
    assert {"log_blood_pressure", "log_med_change"} <= names


def test_logs_a_reading_now_by_default(user):
    assert run(user, "log_blood_pressure", systolic=128, diastolic=82, pulse=64)["success"]
    r = BloodPressureReading.query.one()
    assert (r.systolic, r.diastolic, r.pulse, r.taken_at) == (128, 82, 64, local_dt(day(3), "21:10"))


def test_logs_a_reading_at_a_given_local_time(user):
    run(user, "log_blood_pressure", systolic=131, diastolic=84, date="2026-09-30", time="07:05")
    assert BloodPressureReading.query.one().taken_at == local_dt(day(3), "07:05")


@pytest.mark.parametrize("tool_input", [
    {"systolic": 128},
    {"systolic": 82, "diastolic": 128},
    {"systolic": 128, "diastolic": 82, "date": "2026-10-02"},   # future
])
def test_rejects_bad_readings(user, tool_input):
    assert "error" in run(user, "log_blood_pressure", **tool_input)
    assert BloodPressureReading.query.count() == 0


def test_logs_a_med_change(user):
    assert run(user, "log_med_change", description="Amlodipine 5 → 10 mg", date="2026-10-01",
               time="20:00", notes="Per cardiologist")["success"]
    c = MedicationChange.query.one()
    assert (c.date, c.time, c.description, c.notes) == (date(2026, 10, 1), time(20, 0),
                                                         "Amlodipine 5 → 10 mg", "Per cardiologist")


def test_med_change_defaults_to_today_without_a_time(user):
    run(user, "log_med_change", description="Stopped HCTZ")
    c = MedicationChange.query.one()
    assert (c.date, c.time) == (date(2026, 9, 30), None)


def test_med_change_needs_a_description(user):
    assert "error" in run(user, "log_med_change", description=" ")


def test_context_lists_recent_readings_in_local_time(user):
    log_bp(user, day(2), "21:30", 129, 83, pulse=66)  # Wednesday in UTC
    log_bp(user, day(3), "07:05", 133, 86)
    ctx = section(build_context_summary(user), "Blood pressure")
    assert "2026-09-29 (Tuesday) 9:30 PM: 129/83, pulse 66" in ctx
    assert "2026-09-30 (Wednesday) 7:05 AM: 133/86" in ctx


def test_context_summarizes_each_regimen_and_lists_med_changes(user):
    for i in range(0, 3):
        log_bp(user, day(i), "07:00", 140, 90)
    make_med_change(user, day(3), "Amlodipine 5 → 10 mg", time="07:30", notes="evening dose")
    log_bp(user, day(3), "21:00", 150, 95)
    ctx = section(build_context_summary(user), "Blood pressure")
    assert "Baseline: avg 140/90" in ctx
    assert "3 readings" in ctx
    assert "2026-09-30 7:30 AM: Amlodipine 5 → 10 mg (evening dose)" in ctx
    assert "Amlodipine 5 → 10 mg (since 2026-09-30, day 1)" in ctx


def test_no_bp_section_without_readings_or_changes(user):
    assert "Blood pressure" not in build_context_summary(user)
