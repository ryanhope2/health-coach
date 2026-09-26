"""
Period-level calculations shared by the dashboard, goals page, and AI coach — one place
for "what's the baseline" and "where are we in the period" so they can't drift apart.
"""
from datetime import timedelta

from .models import BodyStat

BASELINE_DAYS = 7


def period_baseline(user_id, period, field):
    """
    Average of a BodyStat field ("weight_lbs" or "body_fat_pct") over the first 7 days
    of the period. Daily scale readings swing 1-2 lb (and several points of body fat),
    so a single starting reading is a poor anchor; a first-week average is the
    starting value compared against everywhere. None if no readings fall in that window.
    """
    if period is None:
        return None
    column = getattr(BodyStat, field)
    rows = (
        BodyStat.query.filter_by(user_id=user_id)
        .filter(column.isnot(None),
                BodyStat.date >= period.start_date,
                BodyStat.date <= period.start_date + timedelta(days=BASELINE_DAYS - 1))
        .all()
    )
    if not rows:
        return None
    return sum(float(getattr(r, field)) for r in rows) / len(rows)


def goal_baseline(goal):
    """Starting value to show for a goal: the period's first-week average for weight/body
    fat, falling back to the single reading captured when the goal was created."""
    field = {"weight": "weight_lbs", "body_fat_pct": "body_fat_pct"}.get(goal.goal_type)
    if field and goal.period is not None:
        baseline = period_baseline(goal.user_id, goal.period, field)
        if baseline is not None:
            return round(baseline, 1)
    return float(goal.starting_value) if goal.starting_value is not None else None


def week_start(d):
    """Sunday on or before d — weeks run Sunday through Saturday everywhere in this app."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


def period_position(period, today):
    """Week N of M (Sun-Sat weeks overlapping the period, so partial first/last weeks count)
    and days left, for headers and the coach context."""
    first_week = week_start(period.start_date)
    total_weeks = (week_start(period.end_date) - first_week).days // 7 + 1
    current_week = (week_start(min(max(today, period.start_date), period.end_date)) - first_week).days // 7 + 1
    return {
        "week": current_week,
        "total_weeks": total_weeks,
        "days_left": max((period.end_date - today).days, 0),
        "ended": today > period.end_date,
    }
