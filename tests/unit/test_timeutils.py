"""Stored timestamps are naive UTC; every day boundary is the user's Eastern day."""
from datetime import date, datetime

from app.timeutils import local_date_to_utc_noon, local_today, to_local_date


def test_evening_eastern_is_still_the_same_day_even_after_utc_midnight():
    # 02:00 UTC on 9/14 is 10pm EDT on 9/13 — the reported "dinner on the wrong day" bug.
    assert to_local_date(datetime(2026, 9, 14, 2, 0)) == date(2026, 9, 13)


def test_just_after_local_midnight_is_the_next_day():
    assert to_local_date(datetime(2026, 9, 14, 4, 30)) == date(2026, 9, 14)  # 12:30am EDT


def test_after_dst_ends_the_offset_is_five_hours():
    # DST ends Nov 1 2026 — inside the Fall period. 04:30 UTC on 11/2 is 11:30pm EST 11/1.
    assert to_local_date(datetime(2026, 11, 2, 4, 30)) == date(2026, 11, 1)
    assert to_local_date(datetime(2026, 11, 2, 5, 30)) == date(2026, 11, 2)


def test_utc_noon_round_trips_to_the_same_local_day_both_sides_of_dst():
    for d in (date(2026, 9, 13), date(2026, 11, 1), date(2026, 11, 5), date(2027, 3, 14)):
        assert to_local_date(local_date_to_utc_noon(d)) == d


def test_local_noon_in_utc_depends_on_dst():
    assert local_date_to_utc_noon(date(2026, 9, 13)) == datetime(2026, 9, 13, 16, 0)
    assert local_date_to_utc_noon(date(2026, 12, 1)) == datetime(2026, 12, 1, 17, 0)


def test_local_today_uses_eastern_not_utc(clock):
    clock.at("2026-09-13 22:00")  # already 9/14 in UTC
    assert local_today() == date(2026, 9, 13)
