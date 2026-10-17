"""Pure blood-pressure math in app/bp_trends.py — no DB. Readings and med changes are built
by hand as the module's own Reading/Change records, in local (Eastern) time."""
from datetime import datetime

import pytest

from app.bp_trends import (Change, Reading, baseline_progress, parse_bp_text, regimen_label,
                           segments, summarize, weeks)
from app.timeutils import USER_TIMEZONE
from tests.builders import SUNDAY, day


def at(offset, hh_mm="07:00"):
    d = day(offset)
    h, m = map(int, hh_mm.split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=USER_TIMEZONE)


def r(offset, hh_mm, sys, dia, pulse=None):
    return Reading(at=at(offset, hh_mm), systolic=sys, diastolic=dia, pulse=pulse)


def change(offset, description="Amlodipine 5 → 10 mg", hh_mm=None):
    return Change(at=at(offset, hh_mm or "00:00"), description=description, has_time=hh_mm is not None)


# --- parse_bp_text ------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("128/82", (128, 82, None)),
    ("128/82 64", (128, 82, 64)),
    ("128 over 82 pulse 64", (128, 82, 64)),
    ("BP 131 / 84, heart rate 70", (131, 84, 70)),
    ("128 82", (128, 82, None)),
    ("  142 over 91  ", (142, 91, None)),
])
def test_parses_typed_or_dictated_readings(text, expected):
    p = parse_bp_text(text)
    assert (p["systolic"], p["diastolic"], p["pulse"]) == expected


@pytest.mark.parametrize("text", ["", "128", "hello", "82/128", "400/82", "128/10"])
def test_rejects_text_that_isnt_a_plausible_reading(text):
    assert parse_bp_text(text) is None


# --- summarize ----------------------------------------------------------------------------

def test_summary_averages_and_splits_morning_from_evening():
    s = summarize([r(0, "07:00", 140, 90, 60), r(0, "07:02", 136, 88, 62),
                   r(0, "21:00", 126, 80, 70), r(1, "07:00", 138, 86)])
    assert (s["n"], s["systolic"], s["diastolic"], s["pulse"]) == (4, 135, 86, 64)
    assert (s["am"]["n"], s["am"]["systolic"], s["am"]["diastolic"]) == (3, 138, 88)
    assert (s["pm"]["n"], s["pm"]["systolic"], s["pm"]["diastolic"]) == (1, 126, 80)
    assert s["days"] == 2


def test_summary_of_nothing_has_no_averages():
    s = summarize([])
    assert (s["n"], s["systolic"], s["am"]["systolic"]) == (0, None, None)


# --- baseline_progress --------------------------------------------------------------------

def test_baseline_counts_days_with_both_a_morning_and_an_evening_reading():
    readings = [r(0, "07:00", 130, 85), r(0, "21:00", 128, 82),
                r(1, "07:00", 130, 85),                          # morning only
                r(2, "21:00", 128, 82),                          # evening only
                r(3, "06:30", 130, 85), r(3, "20:00", 128, 82)]
    b = baseline_progress(readings)
    assert (b["complete_days"], b["mornings"], b["evenings"], b["target"], b["done"]) == (2, 3, 3, 7, False)


def test_baseline_is_done_after_seven_complete_days():
    readings = [x for i in range(7) for x in (r(i, "07:00", 130, 85), r(i, "21:00", 128, 82))]
    assert baseline_progress(readings)["done"]


# --- regimens -----------------------------------------------------------------------------

def test_reading_takes_the_regimen_in_effect_when_it_was_taken():
    changes = [change(3, "A 5 → 10 mg"), change(6, "B added", hh_mm="20:00")]
    assert regimen_label(at(2, "21:00"), changes) == "Baseline"
    assert regimen_label(at(3, "07:00"), changes) == "A 5 → 10 mg"   # date-only change: from midnight
    assert regimen_label(at(6, "07:00"), changes) == "A 5 → 10 mg"   # before that evening's change
    assert regimen_label(at(6, "21:00"), changes) == "B added"


def test_segments_compare_each_regimen_to_the_one_before_after_a_settling_period():
    readings = ([r(i, "07:00", 140, 90) for i in range(0, 5)]       # baseline
                + [r(i, "07:00", 150, 95) for i in range(5, 8)]     # settling — not counted
                + [r(i, "07:00", 130, 84) for i in range(8, 12)])
    base, after = segments(readings, [change(5)], settle_days=3)
    assert (base["label"], base["stats"]["n"], base["stats"]["systolic"]) == ("Baseline", 5, 140)
    assert base["delta"] is None
    assert after["label"] == "Amlodipine 5 → 10 mg"
    assert (len(after["readings"]), after["stats"]["n"], after["stats"]["systolic"]) == (7, 4, 130)
    assert after["counts_from"] == day(8)
    assert after["delta"] == {"systolic": -10, "diastolic": -6}


def test_segment_still_settling_has_no_comparison_yet():
    readings = [r(0, "07:00", 140, 90), r(5, "07:00", 130, 84)]
    _, after = segments(readings, [change(4)], settle_days=7)
    assert after["stats"]["n"] == 0
    assert after["delta"] is None


def test_no_changes_is_one_baseline_segment():
    (only,) = segments([r(0, "07:00", 140, 90)], [], settle_days=7)
    assert (only["label"], only["stats"]["n"]) == ("Baseline", 1)


# --- weeks --------------------------------------------------------------------------------

def test_weeks_run_sunday_to_saturday_newest_first_with_changes_inside():
    readings = [r(-1, "07:00", 150, 95), r(0, "07:00", 140, 90), r(6, "21:00", 130, 80), r(7, "07:00", 128, 80)]
    ws = weeks(readings, [change(3)], as_of=day(8))
    assert [w["start"] for w in ws] == [day(7), SUNDAY, day(-7)]
    this, last, prior = ws
    assert (last["stats"]["n"], last["stats"]["systolic"]) == (2, 135)
    assert [c.description for c in last["changes"]] == ["Amlodipine 5 → 10 mg"]
    assert this["changes"] == [] and this["in_progress"]
    assert [d["date"] for d in last["days"]] == [day(0), day(6)]
