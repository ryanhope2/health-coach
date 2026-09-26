"""
AI coach chat: a conversational assistant with read access to the user's
logged history (body stats, measurements, meals, exercise, goals), and tool
access to actually log new entries on the user's behalf — not just advise.
"""
import json
from datetime import datetime, timedelta

import anthropic

from .progress import goal_baseline, period_baseline, period_position
from .timeutils import local_now, local_today, to_local_date

CHAT_MODEL = "claude-sonnet-4-6"
MAX_TOOL_ROUNDS = 5

SYSTEM_PROMPT = """You are a supportive, knowledgeable fitness and nutrition coach embedded in a \
personal health tracker. You have access to the user's recent logged data, shown below, and tools \
to log new entries directly — weight/body fat, measurements, meals, exercise, and goals.

The "Current date/time" line below IS the actual current date and time, right now, as of this exact \
message — it is computed the instant you're asked, every single turn. It is not a stale snapshot, \
not from when the conversation started, not an estimate. If the user asks what time it is or what \
today's date is, answer directly and confidently from that line — e.g. "It's 8:46 AM EDT on Friday, \
September 11." Never say you don't have a live clock, can't tell what time it is right now, don't \
know how much time has passed, or that they should check their own device — all of that is wrong; \
you genuinely know the current time exactly as well as the user does. Also use it to tell whether \
"today" has rolled over into a new day since the data below was logged, and to infer likely meal type \
(breakfast/lunch/dinner/snack) when the user doesn't specify one and it isn't obvious from context. \
It's in the user's own timezone (US Eastern unless they say they're traveling).

The user's week for tracking/goals purposes always runs Sunday through Saturday — never a \
rolling trailing-7-days window. The "Current week" line below already gives you that week's exact \
start and end dates — use those dates directly rather than computing them yourself from the day \
name; day-of-week arithmetic is exactly the kind of thing that's easy to get subtly wrong, and \
getting it wrong here means blending in days from last week or claiming credit for days that \
haven't happened yet. When the user asks how they're doing "this week," only count entries dated \
from that Sunday through today — never days later in the week (they haven't happened), and never \
days before that Sunday (that's last week). Exercise days are counted by unique calendar dates — \
two workouts logged on the same day count as ONE exercise day, not two. Count distinct dates, \
not log entries.

When the user reports something loggable in their current message (a weight, a meal they ate, a \
workout, a measurement, a new goal), call the matching tool right away instead of just acknowledging \
it in text. The conversation history shown above is a record of what has already happened and been \
logged in previous turns — do NOT re-log anything from earlier messages in this thread; only log \
from the new message you are replying to right now. Never say you've logged, saved, or recorded \
something unless you actually called the tool that turn — if you didn't call a tool, you didn't log \
anything, so don't claim otherwise. Critically: if the user is correcting a mistake you made — \
disputing your count, pointing out a wrong date, questioning your summary — that is NOT a log \
request. Do not call any tool in response to a correction. Just acknowledge the error, correct your \
answer, and move on.

Units: weight in lbs, measurements in inches, dates as YYYY-MM-DD (default to today if the user \
doesn't say). For meals described in words rather than a photo, estimate calories/protein/carbs/fat \
yourself using typical nutrition data and reasonable portion sizes — it's fine to be approximate, and \
mention it's an estimate they can adjust in the Meals tab. If something is genuinely ambiguous (e.g. \
no quantity at all, unclear which measurement they mean), ask a quick clarifying question rather than \
guessing wildly or refusing. Any drink (beer, wine, a cocktail, a shot) is its own category — always \
log it with meal_type "alcohol", never breakfast/lunch/dinner/snack, no matter what time of day it \
was.

After logging a meal or drink with log_meal, always include in your reply: (1) the calories and \
protein you logged for that specific entry, and (2) the updated running total for the day — calories \
and protein so far today, compared against the daily targets if they're set. Use the data already in \
context for existing entries; add the just-logged values to get the new totals. Keep it brief — a \
single line like "That's 450 kcal / 32g protein. You're at 1,200 kcal / 85g protein today (target: \
1,800 kcal / 150g)" is the right amount of detail.

You also have a persistent memory, separate from the visible conversation: "Notes" below (if any) \
are things you've saved about this user's health journey that stay with them forever, not just for \
this chat. Use save_note whenever the user shares something durable and important — an ongoing \
strategy, a motivation, a constraint, context that shapes how you should advise them (e.g. "cutting \
back on alcohol using X approach," "recovering from a knee injury," "why this matters to them"). \
Don't save one-off data points that way — a single meal or workout has its own logging tool. Give \
each note a short, stable, descriptive key (lowercase, underscores, e.g. "alcohol_strategy"); if the \
topic already has a note, saving with the same key updates it in place rather than creating a \
duplicate — do this when the user's situation or approach changes. Use delete_note if something is no \
longer true or relevant. Treat existing notes as already known — don't ask the user to repeat \
something you can see below.

Otherwise, use the logged data and notes to give specific, grounded guidance — reference actual \
numbers, trends, and known context rather than generic advice. Be encouraging but honest; call out \
patterns worth addressing (e.g. protein consistently under target, a stalled weight trend) without \
being preachy. Keep responses conversational and reasonably concise. You are not a doctor — for \
anything medical, suggest they consult one."""

MEASUREMENT_METRICS = ["waist", "hips", "chest", "bicep", "thigh"]
GOAL_TYPES = ["weight", "body_fat_pct"] + MEASUREMENT_METRICS

TOOLS = [
    {
        "name": "log_body_stat",
        "description": "Log the user's weight and/or body fat percentage for a date. If an entry "
                        "already exists for that date, it's updated rather than duplicated.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD, defaults to today"},
                "weight_lbs": {"type": "number"},
                "body_fat_pct": {"type": "number"},
                "notes": {"type": "string"},
            },
        },
    },
    {
        "name": "log_measurement",
        "description": "Log a body measurement (waist, hips, chest, bicep, or thigh) in inches for a date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD, defaults to today"},
                "metric": {"type": "string", "enum": MEASUREMENT_METRICS},
                "value_in": {"type": "number"},
                "notes": {"type": "string"},
            },
            "required": ["metric", "value_in"],
        },
    },
    {
        "name": "log_meal",
        "description": "Log a meal (or drink) the user describes in conversation. Estimate the "
                        "nutrition yourself from the description before calling this. Use "
                        "meal_type 'alcohol' for any beer/wine/cocktail/liquor, regardless of "
                        "what time of day it was, rather than breakfast/lunch/dinner/snack. "
                        "Before calling, check today's meals in the context — if an identical or "
                        "very similar meal is already listed there, do not log it again.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "meal_type": {"type": "string", "enum": ["breakfast", "lunch", "dinner", "snack", "alcohol"]},
                "calories": {"type": "number"},
                "protein_g": {"type": "number"},
                "carbs_g": {"type": "number"},
                "fat_g": {"type": "number"},
                "drinks": {"type": "number", "description": "meal_type 'alcohol' only: how many "
                           "drinks this entry is, as the user would count them — 2 glasses of wine "
                           "= 2, half a glass = 0.5, one cocktail = 1. Defaults to 1."},
            },
            "required": ["description", "calories", "protein_g"],
        },
    },
    {
        "name": "log_exercise",
        "description": (
            "Log a workout or activity the user did. exercise_type determines which fields apply: "
            "'cardio' (Peloton, running, etc.) uses duration_min + calories_burned; "
            "'sets' (curls, pushups, sit-ups, etc.) uses sets + reps + optional weight_lbs; "
            "'hang' (bar hang training) uses sets + hang_seconds + optional rest_seconds. "
            "For bodyweight exercises like pushups/sit-ups use exercise_type='sets' with no weight_lbs. "
            "Before calling, check the exercise data in context — if the same activity on the same "
            "date is already shown there, do not log it again."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD, defaults to today"},
                "activity": {"type": "string", "description": "Name of the activity, e.g. 'Peloton', 'Curls', 'Bar hang'"},
                "exercise_type": {"type": "string", "enum": ["cardio", "sets", "hang"]},
                "duration_min": {"type": "number", "description": "For cardio: total duration in minutes"},
                "calories_burned": {"type": "number", "description": "For cardio: calories burned"},
                "sets": {"type": "number", "description": "For sets/hang: number of sets or hangs"},
                "reps": {"type": "number", "description": "For sets: reps per set"},
                "weight_lbs": {"type": "number", "description": "For sets: weight used in lbs (omit for bodyweight)"},
                "hang_seconds": {"type": "number", "description": "For hang: seconds per hang"},
                "rest_seconds": {"type": "number", "description": "For hang: rest between hangs in seconds"},
                "notes": {"type": "string"},
            },
            "required": ["activity"],
        },
    },
    {
        "name": "set_goal",
        "description": "Set a target for weight, body fat %, or a measurement. It belongs to the "
                        "current tracking period and defaults to that period's end date if no "
                        "target_date is given.",
        "input_schema": {
            "type": "object",
            "properties": {
                "goal_type": {"type": "string", "enum": GOAL_TYPES},
                "target_value": {"type": "number"},
                "target_date": {"type": "string", "description": "YYYY-MM-DD, optional"},
            },
            "required": ["goal_type", "target_value"],
        },
    },
    {
        "name": "set_nutrition_targets",
        "description": "Set the daily calorie and/or protein targets for the current tracking period.",
        "input_schema": {
            "type": "object",
            "properties": {
                "daily_calorie_target": {"type": "number"},
                "daily_protein_target_g": {"type": "number"},
            },
        },
    },
    {
        "name": "save_note",
        "description": "Save or update a durable fact about the user's health journey — an ongoing "
                        "strategy, motivation, constraint, or context that should inform advice in "
                        "every future conversation, not just this one. Saving with a key that already "
                        "exists updates that note instead of duplicating it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Short stable slug, e.g. 'alcohol_strategy'"},
                "content": {"type": "string", "description": "The fact to remember, a sentence or two"},
            },
            "required": ["key", "content"],
        },
    },
    {
        "name": "delete_note",
        "description": "Remove a previously saved note that's no longer true or relevant.",
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
]


def _fmt(value, suffix=""):
    return f"{value}{suffix}" if value is not None else "—"


def _parse_date_or_today(raw):
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            pass
    return local_today()


def _latest_value(user_id, goal_type):
    from .models import BodyStat, Measurement

    if goal_type == "weight":
        row = (BodyStat.query.filter_by(user_id=user_id).filter(BodyStat.weight_lbs.isnot(None))
               .order_by(BodyStat.date.desc()).first())
        return float(row.weight_lbs) if row and row.weight_lbs is not None else None
    if goal_type == "body_fat_pct":
        row = (BodyStat.query.filter_by(user_id=user_id).filter(BodyStat.body_fat_pct.isnot(None))
               .order_by(BodyStat.date.desc()).first())
        return float(row.body_fat_pct) if row and row.body_fat_pct is not None else None
    row = (Measurement.query.filter_by(user_id=user_id, metric=goal_type)
           .order_by(Measurement.date.desc()).first())
    return float(row.value_in) if row else None


def _execute_tool(user_id: int, name: str, tool_input: dict) -> dict:
    from .extensions import db
    from .models import BodyStat, CoachNote, ExerciseEntry, Goal, MealEntry, Measurement, User, normalize_note_key

    try:
        if name == "log_body_stat":
            weight = tool_input.get("weight_lbs")
            body_fat = tool_input.get("body_fat_pct")
            if weight is None and body_fat is None:
                return {"error": "Provide weight_lbs and/or body_fat_pct"}
            d = _parse_date_or_today(tool_input.get("date"))
            existing = BodyStat.query.filter_by(user_id=user_id, date=d).first()
            if existing:
                if weight is not None:
                    existing.weight_lbs = weight
                if body_fat is not None:
                    existing.body_fat_pct = body_fat
                if tool_input.get("notes"):
                    existing.notes = tool_input["notes"]
            else:
                db.session.add(BodyStat(
                    user_id=user_id, date=d, weight_lbs=weight, body_fat_pct=body_fat,
                    notes=tool_input.get("notes"),
                ))
            db.session.commit()
            return {"success": True, "date": str(d), "weight_lbs": weight, "body_fat_pct": body_fat}

        if name == "log_measurement":
            metric = tool_input.get("metric")
            value = tool_input.get("value_in")
            if metric not in MEASUREMENT_METRICS or value is None:
                return {"error": f"metric must be one of {MEASUREMENT_METRICS} and value_in is required"}
            d = _parse_date_or_today(tool_input.get("date"))
            db.session.add(Measurement(
                user_id=user_id, date=d, metric=metric, value_in=value,
                notes=tool_input.get("notes"),
            ))
            db.session.commit()
            return {"success": True, "date": str(d), "metric": metric, "value_in": value}

        if name == "log_meal":
            calories = tool_input.get("calories")
            protein_g = tool_input.get("protein_g")
            if calories is None or protein_g is None:
                return {"error": "calories and protein_g are required"}
            meal_type = tool_input.get("meal_type")
            db.session.add(MealEntry(
                user_id=user_id,
                description=tool_input.get("description"),
                meal_type=meal_type,
                drinks=(tool_input.get("drinks") or 1) if meal_type == "alcohol" else None,
                calories=round(calories),
                protein_g=protein_g,
                carbs_g=tool_input.get("carbs_g"),
                fat_g=tool_input.get("fat_g"),
                status="confirmed",
            ))
            db.session.commit()
            return {"success": True, "calories": calories, "protein_g": protein_g}

        if name == "log_exercise":
            activity = tool_input.get("activity")
            if not activity:
                return {"error": "activity is required"}
            d = _parse_date_or_today(tool_input.get("date"))
            exercise_type = tool_input.get("exercise_type") or "cardio"
            entry = ExerciseEntry(
                user_id=user_id, date=d, activity=activity,
                exercise_type=exercise_type,
                notes=tool_input.get("notes"),
            )
            if exercise_type == "sets":
                entry.sets = tool_input.get("sets")
                entry.reps = tool_input.get("reps")
                entry.weight_lbs = tool_input.get("weight_lbs")
            elif exercise_type == "hang":
                entry.sets = tool_input.get("sets")
                entry.hang_seconds = tool_input.get("hang_seconds")
                entry.rest_seconds = tool_input.get("rest_seconds")
            else:
                entry.duration_min = tool_input.get("duration_min")
                entry.calories_burned = tool_input.get("calories_burned")
            db.session.add(entry)
            db.session.commit()
            return {"success": True, "date": str(d), "activity": activity, "exercise_type": exercise_type}

        if name == "set_goal":
            goal_type = tool_input.get("goal_type")
            target = tool_input.get("target_value")
            if goal_type not in GOAL_TYPES or target is None:
                return {"error": f"goal_type must be one of {GOAL_TYPES} and target_value is required"}
            target_date = None
            if tool_input.get("target_date"):
                try:
                    target_date = datetime.strptime(tool_input["target_date"], "%Y-%m-%d").date()
                except ValueError:
                    target_date = None
            starting = _latest_value(user_id, goal_type)
            period = User.query.get(user_id).current_period()
            if period and not period.contains(local_today()):
                period = None
            db.session.add(Goal(
                user_id=user_id, period_id=period.id if period else None, goal_type=goal_type,
                target_value=target, starting_value=starting,
                target_date=target_date or (period.end_date if period else None), is_active=True,
            ))
            db.session.commit()
            return {"success": True, "goal_type": goal_type, "target_value": target, "starting_value": starting}

        if name == "set_nutrition_targets":
            period = User.query.get(user_id).current_period()
            if not period:
                return {"error": "No tracking period exists yet — the user needs to create one on the Goals page first."}
            if "daily_calorie_target" in tool_input:
                period.daily_calorie_target = round(tool_input["daily_calorie_target"])
            if "daily_protein_target_g" in tool_input:
                period.daily_protein_target_g = tool_input["daily_protein_target_g"]
            db.session.commit()
            return {"success": True}

        if name == "save_note":
            key = normalize_note_key(tool_input.get("key") or "")
            content = (tool_input.get("content") or "").strip()
            if not key or not content:
                return {"error": "key and content are required"}
            existing = CoachNote.query.filter_by(user_id=user_id, key=key).first()
            if existing:
                existing.content = content
            else:
                db.session.add(CoachNote(user_id=user_id, key=key, content=content))
            db.session.commit()
            return {"success": True, "key": key}

        if name == "delete_note":
            key = normalize_note_key(tool_input.get("key") or "")
            note = CoachNote.query.filter_by(user_id=user_id, key=key).first()
            if not note:
                return {"error": f"No note found with key '{key}'"}
            db.session.delete(note)
            db.session.commit()
            return {"success": True}

        return {"error": f"unknown tool {name}"}
    except Exception as e:
        db.session.rollback()
        return {"error": str(e)}


def build_context_summary(user) -> str:
    """Summarize the user's recent data for the system prompt."""
    from .models import BodyStat, CoachNote, ExerciseEntry, Goal, MealEntry, Measurement

    today = local_today()
    now_local = local_now()
    # Sunday-Saturday calendar week containing today, computed here rather than left for the
    # model to derive from the day name — day-of-week arithmetic is an easy thing to get subtly
    # wrong, and getting it wrong means blending in last week's days or crediting future ones.
    days_since_sunday = (today.weekday() + 1) % 7
    week_start = today - timedelta(days=days_since_sunday)
    week_end = week_start + timedelta(days=6)
    lines = [
        f"User: {user.label}",
        f"Current date/time: {now_local.strftime('%A, %B %-d, %Y at %-I:%M %p %Z')}",
        f"Current week (Sun-Sat): {week_start} ({week_start.strftime('%A')}) to "
        f"{week_end} ({week_end.strftime('%A')}) — today is day "
        f"{(today - week_start).days + 1} of 7",
    ]

    notes = CoachNote.query.filter_by(user_id=user.id).order_by(CoachNote.updated_at.desc()).all()
    if notes:
        lines.append("\nNotes (persistent — known regardless of how long this conversation has been going):")
        for n in notes:
            lines.append(f"  [{n.key}] {n.content}")

    period = user.current_period()
    if period:
        pos = period_position(period, today)
        status = ("ended" if pos["ended"]
                  else f"week {pos['week']} of {pos['total_weeks']}, {pos['days_left']} days left")
        lines.append(
            f"\nCurrent tracking period: \"{period.name}\", {period.start_date} to {period.end_date} ({status})"
        )
        baselines = [
            f"{label} {value:.1f}{unit}"
            for label, field, unit in (("weight", "weight_lbs", " lbs"), ("body fat", "body_fat_pct", "%"))
            if (value := period_baseline(user.id, period, field)) is not None
        ]
        if baselines:
            lines.append(f"Period baseline (average of first 7 days): {', '.join(baselines)}")
        lines.append(
            f"Daily targets: {_fmt(period.daily_calorie_target, ' kcal')}, "
            f"{_fmt(period.daily_protein_target_g, 'g protein')}; "
            f"exercise target {_fmt(period.weekly_exercise_days_target, ' days/week')}"
        )

    recent_stats = (
        BodyStat.query.filter_by(user_id=user.id)
        .filter(BodyStat.date >= today - timedelta(days=60))
        .order_by(BodyStat.date.asc())
        .all()
    )
    if recent_stats:
        lines.append("\nWeight / body fat (last 60 days, oldest to newest):")
        for s in recent_stats:
            lines.append(f"  {s.date} ({s.date.strftime('%A')}): weight={_fmt(s.weight_lbs, ' lbs')}, body_fat={_fmt(s.body_fat_pct, '%')}")

    recent_measurements = (
        Measurement.query.filter_by(user_id=user.id)
        .filter(Measurement.date >= today - timedelta(days=90))
        .order_by(Measurement.date.asc())
        .all()
    )
    if recent_measurements:
        lines.append("\nMeasurements (last 90 days):")
        for m in recent_measurements:
            lines.append(f"  {m.date} ({m.date.strftime('%A')}): {m.metric}={m.value_in} in")

    recent_meals = (
        MealEntry.query.filter_by(user_id=user.id, status="confirmed")
        .filter(MealEntry.logged_at >= today - timedelta(days=14))
        .order_by(MealEntry.logged_at.asc())
        .all()
    )
    if recent_meals:
        lines.append("\nMeals (last 14 days, daily totals):")
        by_day = {}
        for m in recent_meals:
            d = to_local_date(m.logged_at)
            totals = by_day.setdefault(d, {"calories": 0, "protein": 0, "drinks": 0})
            totals["calories"] += m.calories or 0
            totals["protein"] += float(m.protein_g or 0)
            totals["drinks"] += m.drink_count
        for d, totals in sorted(by_day.items()):
            drinks = f", {totals['drinks']:g} drink(s)" if totals["drinks"] else ""
            lines.append(f"  {d} ({d.strftime('%A')}): {totals['calories']} kcal, {totals['protein']:.0f}g protein{drinks}")

        # Line-item detail for the last 3 days (today + yesterday + day before).
        # Daily totals alone don't let the coach comment on what was actually eaten,
        # and showing descriptions for recent days also lets the coach recognize items
        # already logged in earlier conversation turns so it doesn't re-log them.
        detail_cutoff = today - timedelta(days=2)
        recent_detail_meals = [m for m in recent_meals if to_local_date(m.logged_at) >= detail_cutoff]
        if recent_detail_meals:
            by_day_detail: dict = {}
            for m in recent_detail_meals:
                by_day_detail.setdefault(to_local_date(m.logged_at), []).append(m)
            for d in sorted(by_day_detail.keys(), reverse=True):
                if d == today:
                    day_label = f"Today ({d})"
                elif d == today - timedelta(days=1):
                    day_label = f"Yesterday ({d})"
                else:
                    day_label = f"{d} ({d.strftime('%A')})"
                lines.append(f"\n{day_label} meals in detail:")
                for m in by_day_detail[d]:
                    label = (m.meal_type or "meal").capitalize()
                    if m.meal_type == "alcohol":
                        label += f", {m.drink_count:g} drink(s)"
                    desc = m.description or "(no description)"
                    lines.append(
                        f"  [{label}] {desc} — {_fmt(m.calories, ' kcal')}, "
                        f"{_fmt(m.protein_g, 'g protein')}, {_fmt(m.carbs_g, 'g carbs')}, "
                        f"{_fmt(m.fat_g, 'g fat')}"
                    )

    recent_exercise = (
        ExerciseEntry.query.filter_by(user_id=user.id)
        .filter(ExerciseEntry.date >= today - timedelta(days=14))
        .order_by(ExerciseEntry.date.asc())
        .all()
    )
    if recent_exercise:
        this_week = [e for e in recent_exercise if e.date >= week_start]
        prior = [e for e in recent_exercise if e.date < week_start]

        def _fmt_exercise(e):
            if e.exercise_type == "sets":
                detail = f"{e.sets or '?'}×{e.reps or '?'}"
                if e.weight_lbs:
                    detail += f" @ {e.weight_lbs} lbs"
                else:
                    detail += " (bodyweight)"
            elif e.exercise_type == "hang":
                detail = f"{e.sets or '?'}× {e.hang_seconds or '?'}s"
                if e.rest_seconds:
                    detail += f" ({e.rest_seconds}s rest)"
            else:
                detail = _fmt(e.duration_min, " min")
                if e.calories_burned:
                    detail += f", {e.calories_burned} cal burned"
            return (
                f"  {e.date} ({e.date.strftime('%A')}): {e.activity}, {detail}"
                + (f" — {e.notes}" if e.notes else "")
            )

        lines.append(f"\nExercise — this week ({week_start} to {week_end}), {len(this_week)} day(s) so far:")
        if this_week:
            for e in this_week:
                lines.append(_fmt_exercise(e))
        else:
            lines.append("  (none yet this week)")

        if prior:
            lines.append("Prior exercise (last 14 days):")
            for e in prior:
                lines.append(_fmt_exercise(e))

    active_goals = Goal.query.filter_by(user_id=user.id, is_active=True).all()
    if active_goals:
        lines.append("\nActive goals:")
        for g in active_goals:
            target_date = f" by {g.target_date} ({g.target_date.strftime('%A')})" if g.target_date else ""
            lines.append(f"  {g.goal_type}: target {g.target_value}{target_date} (starting from {goal_baseline(g)})")

    if len(lines) == 1:
        lines.append("\n(No data logged yet — encourage the user to start logging weight, meals, and exercise.)")

    return "\n".join(lines)


def get_response(api_key: str, user, conversation_history: list[dict], new_message: str) -> str:
    """
    conversation_history: list of {"role": "user"|"assistant", "content": str}, oldest first.
    Runs a tool-use loop so the coach can actually log data, not just talk about it.
    Returns the assistant's final reply text.
    """
    client = anthropic.Anthropic(api_key=api_key)

    context = build_context_summary(user)
    system = f"{SYSTEM_PROMPT}\n\n--- User's current data ---\n{context}"

    messages = list(conversation_history) + [{"role": "user", "content": new_message}]

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=CHAT_MODEL,
            max_tokens=1024,
            system=system,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if b.type == "text")

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = _execute_tool(user.id, block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                })
        messages.append({"role": "user", "content": tool_results})

    return "I made some updates but had trouble wrapping up the reply — check your logs to confirm everything saved."
