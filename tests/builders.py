"""
Plain functions for putting rows in the test DB with sensible defaults. Each takes the
owning user first and returns the committed row. Pass only what the test is about.

Dates: tests anchor on a fixed Sunday (SUNDAY) rather than the real today — use
`day(n)` for SUNDAY + n days.
"""
from datetime import date, datetime, timedelta
from datetime import time as clock_time
from zoneinfo import ZoneInfo

from app.extensions import db
from app.models import (BloodPressureReading, BodyStat, ChatMessage, CoachNote, ExerciseEntry, Goal, MealEntry,
                        Measurement, MedicationChange, SavedMeal, TrackingPeriod, WeeklyRecap)
from app.timeutils import USER_TIMEZONE

UTC = ZoneInfo("UTC")

SUNDAY = date(2026, 9, 27)  # the week runs Sun 9/27 - Sat 10/3


def day(offset):
    return SUNDAY + timedelta(days=offset)


def local_dt(d, hh_mm="12:00"):
    """Naive-UTC datetime (how every DateTime column is stored) for a local Eastern
    date + time — e.g. local_dt(day(0), "21:30") is 9:30pm Sunday Eastern."""
    h, m = map(int, hh_mm.split(":"))
    local = datetime(d.year, d.month, d.day, h, m, tzinfo=USER_TIMEZONE)
    return local.astimezone(UTC).replace(tzinfo=None)


def _save(row):
    db.session.add(row)
    db.session.commit()
    return row


def make_period(user, start=None, end=None, name="Fall", calories=2000, protein=150, exercise_days=4):
    start = start or day(-14)
    return _save(TrackingPeriod(
        user_id=user.id, name=name, start_date=start, end_date=end or start + timedelta(days=76),
        daily_calorie_target=calories, daily_protein_target_g=protein,
        weekly_exercise_days_target=exercise_days))


def log_weight(user, d, weight=None, body_fat=None, notes=None):
    return _save(BodyStat(user_id=user.id, date=d, weight_lbs=weight, body_fat_pct=body_fat, notes=notes))


def log_measurement(user, d, metric="waist", value=36.0):
    return _save(Measurement(user_id=user.id, date=d, metric=metric, value_in=value))


def log_meal(user, d=None, time="12:00", calories=500, protein=30, meal_type="lunch",
             description="food", status="confirmed", drinks=None, at=None):
    """`at` (naive UTC) overrides d/time when a test needs an exact stored instant."""
    return _save(MealEntry(
        user_id=user.id, logged_at=at or local_dt(d or SUNDAY, time), meal_type=meal_type,
        description=description, calories=calories, protein_g=protein, status=status, drinks=drinks))


def log_drink(user, d=None, time="19:00", drinks=1, calories=150):
    return log_meal(user, d, time, calories=calories, protein=0, meal_type="alcohol",
                    description="drink", drinks=drinks)


def log_workout(user, d, exercise_type="cardio", activity="Peloton", **fields):
    if exercise_type in ("cardio", None):
        fields.setdefault("duration_min", 20)
    return _save(ExerciseEntry(user_id=user.id, date=d, activity=activity,
                               exercise_type=exercise_type, **fields))


def make_goal(user, period=None, goal_type="weight", target=200, starting=None, active=True):
    return _save(Goal(user_id=user.id, period_id=period.id if period else None, goal_type=goal_type,
                      target_value=target, starting_value=starting, is_active=active,
                      target_date=period.end_date if period else None))


def make_note(user, key="travel", content="At Disney this week"):
    return _save(CoachNote(user_id=user.id, key=key, content=content))


def make_saved_meal(user, name="Oatmeal bowl", meal_type="breakfast", calories=350, protein=20):
    return _save(SavedMeal(user_id=user.id, name=name, meal_type=meal_type,
                           calories=calories, protein_g=protein))


def make_chat(user, role="user", content="hi", at=None):
    return _save(ChatMessage(user_id=user.id, role=role, content=content,
                             created_at=at or datetime.utcnow()))


def make_recap(user, week_start=SUNDAY, content="A recap.", headline="Headline.", covers_through=None):
    return _save(WeeklyRecap(user_id=user.id, week_start=week_start, content=content, headline=headline,
                             covers_through=covers_through or week_start + timedelta(days=6)))


def log_bp(user, d=None, time="07:00", systolic=130, diastolic=85, pulse=None, notes=None):
    return _save(BloodPressureReading(user_id=user.id, taken_at=local_dt(d or SUNDAY, time),
                                      systolic=systolic, diastolic=diastolic, pulse=pulse, notes=notes))


def make_med_change(user, d=None, description="Amlodipine 5 → 10 mg", time=None, notes=None):
    """`time` is "HH:MM" local, or None for a date-only change."""
    t = clock_time(*map(int, time.split(":"))) if time else None
    return _save(MedicationChange(user_id=user.id, date=d or SUNDAY, time=t,
                                  description=description, notes=notes))
