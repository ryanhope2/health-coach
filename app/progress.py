"""
Period-level calculations shared by the dashboard, goals page, and AI coach — one place
for "what's the baseline" and "where are we in the period" so they can't drift apart.
"""
from datetime import datetime, timedelta

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


# --- Progress page / weekly recap calculations --------------------------------------
# Everything below takes an `as_of` date instead of reading the clock, so the same code
# answers "this week so far" for the page and "how did that finished week go" for a
# recap generated days later.

CALORIE_TOLERANCE = 0.05    # "in range" = at most 5% over the daily calorie target
PACE_TOLERANCE_LBS = 0.5    # within this of the pace line counts as "on pace"
PROJECTION_MIN_DAYS = 14    # don't extrapolate a trend line from less than two weeks of data
STRENGTH_TYPES = ("sets", "hang")


def calorie_cap(period):
    if not period or not period.daily_calorie_target:
        return None
    return round(period.daily_calorie_target * (1 + CALORIE_TOLERANCE))


def daily_rollup(user_id, start, end):
    """
    {date: {...}} for every date in [start, end]: meal totals from confirmed meals grouped by
    local date, drinks, exercise, and that day's scale reading. A day with no confirmed meal
    has meals_logged False — it's left out of calorie/protein averages rather than counted
    as a 0-calorie day.
    """
    from .models import ExerciseEntry, MealEntry
    from .timeutils import to_local_date

    days = {}
    d = start
    while d <= end:
        days[d] = {"date": d, "calories": 0, "protein": 0.0, "drinks": 0.0, "drink_calories": 0,
                   "meals_logged": False, "exercise": set(), "weight": None, "body_fat": None}
        d += timedelta(days=1)

    # Loose UTC bounds as full datetimes (see the bare-date comparison gotcha in CLAUDE.md),
    # then the exact local-day check in Python.
    lower = datetime.combine(start - timedelta(days=1), datetime.min.time())
    upper = datetime.combine(end + timedelta(days=2), datetime.min.time())
    meals = (MealEntry.query.filter_by(user_id=user_id, status="confirmed")
             .filter(MealEntry.logged_at >= lower, MealEntry.logged_at < upper).all())
    for m in meals:
        day = days.get(to_local_date(m.logged_at))
        if day is None:
            continue
        day["meals_logged"] = True
        day["calories"] += m.calories or 0
        day["protein"] += float(m.protein_g or 0)
        if m.meal_type == "alcohol":
            day["drinks"] += m.drink_count
            day["drink_calories"] += m.calories or 0

    for e in (ExerciseEntry.query.filter_by(user_id=user_id)
              .filter(ExerciseEntry.date >= start, ExerciseEntry.date <= end).all()):
        days[e.date]["exercise"].add("strength" if e.exercise_type in STRENGTH_TYPES else "cardio")

    for s in (BodyStat.query.filter_by(user_id=user_id)
              .filter(BodyStat.date >= start, BodyStat.date <= end).all()):
        days[s.date]["weight"] = float(s.weight_lbs) if s.weight_lbs is not None else None
        days[s.date]["body_fat"] = float(s.body_fat_pct) if s.body_fat_pct is not None else None

    return days


def _avg(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def week_summary(rollup, period, wk_start, as_of):
    """
    Sun-Sat week starting wk_start, clipped to the period and to as_of. Calorie/protein
    averages and in-range counts use completed days only (as_of itself is still in
    progress); drinks and exercise count everything through as_of, since a drink or a
    workout today has already happened.
    """
    first = max(wk_start, period.start_date)
    last = min(wk_start + timedelta(days=6), period.end_date, as_of)
    days = [rollup[d] for d in sorted(rollup) if first <= d <= last]
    finished_meal_days = [x for x in days if x["meals_logged"] and x["date"] < as_of]
    cap = calorie_cap(period)
    protein_target = float(period.daily_protein_target_g) if period.daily_protein_target_g else None
    exercise_target = period.weekly_exercise_days_target or 4
    exercise_days = [x for x in days if x["exercise"]]
    return {
        "start": wk_start,
        "first": first,
        "last": last,
        "partial": first > wk_start or wk_start + timedelta(days=6) > period.end_date,
        "in_progress": first <= as_of <= wk_start + timedelta(days=6) and as_of <= period.end_date,
        "days": days,
        "meal_days": len(finished_meal_days),
        "calories_avg": _avg([x["calories"] for x in finished_meal_days]),
        "calories_in_range": sum(1 for x in finished_meal_days if cap and x["calories"] <= cap),
        "protein_avg": _avg([x["protein"] for x in finished_meal_days]),
        "protein_hit": sum(1 for x in finished_meal_days if protein_target and x["protein"] >= protein_target),
        "drinks": sum(x["drinks"] for x in days),
        "drinking_days": sum(1 for x in days if x["drinks"]),
        "drink_calories": sum(x["drink_calories"] for x in days),
        "exercise_days": len(exercise_days),
        "cardio_days": sum(1 for x in exercise_days if "cardio" in x["exercise"]),
        "strength_days": sum(1 for x in exercise_days if "strength" in x["exercise"]),
        "exercise_met": len(exercise_days) >= exercise_target,
        "weight_avg": _avg([x["weight"] for x in days]),
        "body_fat_avg": _avg([x["body_fat"] for x in days]),
    }


def period_weeks(user_id, period, as_of):
    """Summaries for every Sun-Sat week of the period through as_of, newest first."""
    last_day = min(as_of, period.end_date)
    rollup = daily_rollup(user_id, period.start_date, last_day)
    weeks = []
    wk = week_start(period.start_date)
    while wk <= last_day:
        weeks.append(week_summary(rollup, period, wk, as_of))
        wk += timedelta(days=7)
    return list(reversed(weeks))


def weight_progress(user_id, period, goal, as_of):
    """
    Everything the weight card and chart need: baseline (first-week average), current
    7-day average, goal pace line and status, and — once there's enough data — a
    least-squares projection to the period's end date.
    """
    readings = [
        (s.date, float(s.weight_lbs)) for s in
        BodyStat.query.filter_by(user_id=user_id)
        .filter(BodyStat.weight_lbs.isnot(None),
                BodyStat.date >= period.start_date, BodyStat.date <= min(as_of, period.end_date))
        .order_by(BodyStat.date).all()
    ]
    total_days = (period.end_date - period.start_date).days or 1

    def offset(d):
        return (d - period.start_date).days

    rolling = []
    for d, _ in readings:
        window = [w for rd, w in readings if d - timedelta(days=6) <= rd <= d]
        rolling.append((d, sum(window) / len(window)))

    baseline = period_baseline(user_id, period, "weight_lbs")
    recent = [(d, w) for d, w in readings if d > as_of - timedelta(days=7)]
    current = _avg([w for _, w in recent])
    target = float(goal.target_value) if goal else None

    pace = on_pace = status = gap = None
    if baseline is not None and target is not None:
        pace = (target - baseline) / total_days  # lbs/day, negative when losing
        if current is not None:
            # Compare at the middle of the readings being averaged, not today — a trailing
            # 7-day average lags the calendar by a few days.
            mid = sum(offset(d) for d, _ in recent) / len(recent)
            on_pace = baseline + pace * mid
            gap = (current - on_pace) * (1 if target < baseline else -1)  # positive = behind
            status = "behind" if gap > PACE_TOLERANCE_LBS else "ahead" if gap < -PACE_TOLERANCE_LBS else "on pace"

    projection = None
    if len(readings) >= 5 and (as_of - period.start_date).days >= PROJECTION_MIN_DAYS:
        xs = [offset(d) for d, _ in readings]
        ys = [w for _, w in readings]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        if sxx:
            slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
            fit = lambda x: my + slope * (x - mx)  # noqa: E731
            now_x = offset(min(as_of, period.end_date))
            projection = {"per_week": slope * 7, "end_value": fit(total_days),
                          "line": [(now_x, fit(now_x)), (total_days, fit(total_days))]}

    return {
        "baseline": baseline,
        "current": current,
        "target": target,
        "pace_per_week": pace * 7 if pace is not None else None,
        "on_pace_value": on_pace,
        "status": status,
        "gap": abs(gap) if gap is not None else None,
        "projection": projection,
        "chart": {
            "start": period.start_date.isoformat(),
            "total_days": total_days,
            "today": offset(min(as_of, period.end_date)),
            "readings": [(offset(d), w) for d, w in readings],
            "rolling": [(offset(d), round(w, 2)) for d, w in rolling],
            "pace": [(0, baseline), (total_days, target)] if baseline is not None and target is not None else None,
            "projection": projection["line"] if projection else None,
            "target": target,
        },
    }
