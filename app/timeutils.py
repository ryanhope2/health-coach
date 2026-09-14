"""
Single source of truth for "what day is it for the user right now" — every place in the
app that needs today's date or needs to turn a stored UTC timestamp into a calendar day
should go through here instead of using `date.today()`/`datetime.utcnow()` directly.

The server runs in UTC; the user is in US Eastern unless traveling. This is a fixed
assumption for now rather than a stored per-user setting — revisit if travel-driven
timezone changes turn out to matter often enough to be worth tracking properly.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

USER_TIMEZONE = ZoneInfo("America/New_York")
_UTC = ZoneInfo("UTC")


def local_now() -> datetime:
    return datetime.now(USER_TIMEZONE)


def local_today() -> date:
    return local_now().date()


def to_local_date(naive_utc_dt: datetime) -> date:
    """Convert a naive-UTC datetime (as stored in every DateTime column in this app) to
    the calendar date it falls on in the user's local timezone. SQLite has no
    timezone-aware date truncation, so any day-grouping/boundary logic against a
    DateTime column must go through this in Python rather than `func.date()` in SQL."""
    return naive_utc_dt.replace(tzinfo=_UTC).astimezone(USER_TIMEZONE).date()


def local_date_to_utc_noon(d: date) -> datetime:
    """Return a naive-UTC datetime representing noon on day `d` in the user's timezone.
    Used when backdating a meal entry — we don't know the actual time, so noon places it
    safely in the middle of the day and avoids any UTC-offset edge that could shift the
    entry to the wrong calendar day."""
    local_noon = datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=USER_TIMEZONE)
    return local_noon.astimezone(_UTC).replace(tzinfo=None)
