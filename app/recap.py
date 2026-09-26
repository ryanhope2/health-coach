"""
AI weekly recap: a short written summary of one Sun-Sat week, grounded in the same numbers
the Progress page shows (computed by app/progress.py and handed to the model, never
re-derived by it) plus the context that explains them — CoachNotes, what was actually
eaten, the workouts, and that week's coach chat.
"""
from datetime import datetime, timedelta

import anthropic

from . import progress
from .ai_coach import CHAT_MODEL
from .extensions import db
from .models import ChatMessage, CoachNote, ExerciseEntry, Goal, MealEntry, WeeklyRecap
from .timeutils import local_today, to_local_date

PRIOR_WEEKS = 3
MAX_CHAT_MESSAGES = 60
MAX_CHAT_CHARS = 400

RECAP_PROMPT = """You write the weekly recap on a personal fitness tracker's Progress page. The \
person reads it to see, at a glance, how their week actually went against their goals.

Write 4-6 sentences of plain prose, in second person ("you"). No headings, bullets, or markdown. \
Cover what went well, what slipped, and where they stand against their goal pace, using the \
specific numbers given below — never compute or invent your own totals. Use the notes, meals, \
workouts, and chat to explain *why* a week looked the way it did (travel, an event, an injury) \
rather than treating every week as ordinary. End with one concrete, specific thing to focus on \
next week. Be direct and honest, not a cheerleader — no exclamation points, no generic praise.{in_progress}

{data}"""

IN_PROGRESS_NOTE = """

This week is still in progress (through {through}), so describe it as "so far" and make the \
closing focus about the rest of this week instead of next week."""


def _fmt(value, spec=".0f", suffix=""):
    return "n/a" if value is None else f"{value:{spec}}{suffix}"


def _week_line(w, cap):
    return (
        f"calories avg {_fmt(w['calories_avg'])} over {w['meal_days']} logged day(s), "
        f"{w['calories_in_range']} of {w['meal_days']} at or under {cap or 'n/a'}; "
        f"protein avg {_fmt(w['protein_avg'], suffix='g')}, target hit {w['protein_hit']} day(s); "
        f"drinks {w['drinks']:g} on {w['drinking_days']} day(s) ({w['drink_calories']} kcal); "
        f"exercise {w['exercise_days']} day(s) ({w['cardio_days']} cardio, {w['strength_days']} strength); "
        f"weight avg {_fmt(w['weight_avg'], '.1f')}, body fat avg {_fmt(w['body_fat_avg'], '.1f', '%')}"
    )


def build_recap_data(user, period, wk_start, as_of):
    wk_end = wk_start + timedelta(days=6)
    weeks = progress.period_weeks(user.id, period, as_of)
    this_week = next(w for w in weeks if w["start"] == wk_start)
    prior = [w for w in weeks if w["start"] < wk_start][:PRIOR_WEEKS]
    cap = progress.calorie_cap(period)
    goal = Goal.query.filter_by(user_id=user.id, period_id=period.id, goal_type="weight", is_active=True).first()
    wp = progress.weight_progress(user.id, period, goal, as_of)
    pos = progress.period_position(period, min(as_of, wk_end))

    lines = [
        f'Tracking period "{period.name}": {period.start_date} to {period.end_date}, '
        f"this is week {pos['week']} of {pos['total_weeks']}.",
        f"Targets: calories at or under {cap or 'n/a'}/day (target {period.daily_calorie_target} + 5%), "
        f"protein {period.daily_protein_target_g or 'n/a'}g/day, exercise {period.weekly_exercise_days_target or 4}+ days/week.",
        f"Weight: first-week baseline {_fmt(wp['baseline'], '.1f')}, current 7-day avg {_fmt(wp['current'], '.1f')}, "
        f"goal {_fmt(wp['target'], '.1f')} by {period.end_date}.",
    ]
    if wp["status"]:
        lines.append(f"Goal pace: {wp['pace_per_week']:.2f} lb/week needed; currently {wp['status']}"
                     f" ({wp['gap']:.1f} lb from the pace line).")
    if wp["projection"]:
        lines.append(f"Trend: {wp['projection']['per_week']:.2f} lb/week, projecting {wp['projection']['end_value']:.1f} at period end.")

    lines.append(f"\nTHIS WEEK ({this_week['first']} to {this_week['last']}): {_week_line(this_week, cap)}")
    lines.append("Day by day:")
    for d in this_week["days"]:
        parts = [f"{d['calories']} kcal, {d['protein']:.0f}g protein" if d["meals_logged"] else "no meals logged"]
        if d["drinks"]:
            parts.append(f"{d['drinks']:g} drink(s)")
        if d["exercise"]:
            parts.append("exercise: " + "+".join(sorted(d["exercise"])))
        if d["weight"] is not None:
            parts.append(f"weight {d['weight']:.1f}")
        lines.append(f"  {d['date']:%a %m/%d}: " + ", ".join(parts))

    if prior:
        lines.append("\nPREVIOUS WEEKS (for comparison):")
        for w in prior:
            lines.append(f"  Week of {w['start']}{' (partial)' if w['partial'] else ''}: {_week_line(w, cap)}")

    notes = CoachNote.query.filter_by(user_id=user.id).order_by(CoachNote.updated_at.desc()).all()
    if notes:
        lines.append("\nNOTES the person has shared (context, strategies, plans):")
        lines += [f"  [{n.key}] {n.content}" for n in notes]

    lower = datetime.combine(wk_start - timedelta(days=1), datetime.min.time())
    upper = datetime.combine(wk_end + timedelta(days=2), datetime.min.time())
    in_week = lambda dt: this_week["first"] <= to_local_date(dt) <= this_week["last"]  # noqa: E731

    meals = [m for m in MealEntry.query.filter_by(user_id=user.id, status="confirmed")
             .filter(MealEntry.logged_at >= lower, MealEntry.logged_at < upper)
             .order_by(MealEntry.logged_at).all() if in_week(m.logged_at)]
    if meals:
        lines.append("\nWHAT WAS EATEN/DRUNK:")
        for m in meals:
            lines.append(f"  {to_local_date(m.logged_at):%a} [{m.meal_type or 'meal'}] "
                         f"{(m.description or '')[:120]} ({m.calories or '?'} kcal)")

    workouts = (ExerciseEntry.query.filter_by(user_id=user.id)
                .filter(ExerciseEntry.date >= this_week["first"], ExerciseEntry.date <= this_week["last"])
                .order_by(ExerciseEntry.date).all())
    if workouts:
        lines.append("\nWORKOUTS:")
        for e in workouts:
            lines.append(f"  {e.date:%a} {e.activity}" + (f" — {e.notes[:120]}" if e.notes else ""))

    chat = [c for c in ChatMessage.query.filter_by(user_id=user.id)
            .filter(ChatMessage.created_at >= lower, ChatMessage.created_at < upper)
            .order_by(ChatMessage.created_at).all() if in_week(c.created_at)][-MAX_CHAT_MESSAGES:]
    if chat:
        lines.append("\nCOACH CHAT THIS WEEK:")
        for c in chat:
            lines.append(f"  {to_local_date(c.created_at):%a} {c.role}: {c.content[:MAX_CHAT_CHARS]}")

    return "\n".join(lines), this_week


def generate_recap(api_key, user, period, wk_start, as_of=None):
    """Write (or rewrite) the recap for the week starting wk_start. as_of defaults to the
    day after the week ends for a finished week, or today for the current one."""
    today = local_today()
    wk_end = wk_start + timedelta(days=6)
    if as_of is None:
        as_of = min(wk_end + timedelta(days=1), today)
    data, this_week = build_recap_data(user, period, wk_start, as_of)
    in_progress = as_of <= wk_end
    prompt = RECAP_PROMPT.format(
        data=data,
        in_progress=IN_PROGRESS_NOTE.format(through=this_week["last"]) if in_progress else "",
    )

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=CHAT_MODEL, max_tokens=600, messages=[{"role": "user", "content": prompt}],
    )
    content = "".join(b.text for b in response.content if b.type == "text").strip()

    recap = WeeklyRecap.query.filter_by(user_id=user.id, week_start=wk_start).first()
    if recap is None:
        recap = WeeklyRecap(user_id=user.id, week_start=wk_start)
        db.session.add(recap)
    recap.content = content
    recap.covers_through = this_week["last"]
    recap.generated_at = datetime.utcnow()
    db.session.commit()
    return recap


def latest_recap(user_id):
    return (WeeklyRecap.query.filter_by(user_id=user_id)
            .order_by(WeeklyRecap.week_start.desc()).first())
