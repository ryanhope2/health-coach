from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from ..extensions import db
from ..models import ExerciseEntry
from ..timeutils import local_today

exercise_bp = Blueprint("exercise", __name__, url_prefix="/exercise")


def _current_user_id():
    return session["user_id"]


@exercise_bp.route("/")
def index():
    entries = (
        ExerciseEntry.query.filter_by(user_id=_current_user_id())
        .order_by(ExerciseEntry.date.desc(), ExerciseEntry.created_at.desc())
        .limit(90)
        .all()
    )
    return render_template("exercise/index.html", entries=entries, today=local_today().isoformat())


@exercise_bp.route("/new", methods=["POST"])
def new():
    activity = request.form.get("activity", "").strip()
    if not activity:
        flash("Enter an activity.", "error")
        return redirect(_safe_next())

    entry_date = _parse_date(request.form.get("date")) or local_today()
    exercise_type = request.form.get("exercise_type") or "cardio"
    notes = request.form.get("notes", "").strip() or None

    entry = ExerciseEntry(
        user_id=_current_user_id(), date=entry_date, activity=activity,
        exercise_type=exercise_type, notes=notes,
    )

    if exercise_type == "sets":
        entry.sets = _parse_int(request.form.get("sets"))
        entry.reps = _parse_int(request.form.get("reps"))
        entry.weight_lbs = _parse_float(request.form.get("weight_lbs"))
    elif exercise_type == "hang":
        entry.sets = _parse_int(request.form.get("sets"))
        entry.hang_seconds = _parse_int(request.form.get("hang_seconds"))
        entry.rest_seconds = _parse_int(request.form.get("rest_seconds"))
    else:
        entry.duration_min = _parse_int(request.form.get("duration_min"))
        entry.calories_burned = _parse_int(request.form.get("calories_burned"))

    db.session.add(entry)
    db.session.commit()
    flash("Logged.", "success")
    return redirect(_safe_next())


@exercise_bp.route("/<int:entry_id>/edit", methods=["POST"])
def edit(entry_id):
    entry = ExerciseEntry.query.filter_by(id=entry_id, user_id=_current_user_id()).first_or_404()

    activity = request.form.get("activity", "").strip()
    if not activity:
        flash("Enter an activity.", "error")
        return redirect(url_for("exercise.index"))

    exercise_type = request.form.get("exercise_type") or "cardio"
    entry.date = _parse_date(request.form.get("date")) or entry.date
    entry.activity = activity
    entry.exercise_type = exercise_type
    entry.notes = request.form.get("notes", "").strip() or None

    # Clear all type-specific fields, then set only the ones for the current type
    entry.duration_min = entry.calories_burned = None
    entry.sets = entry.reps = entry.weight_lbs = None
    entry.hang_seconds = entry.rest_seconds = None

    if exercise_type == "sets":
        entry.sets = _parse_int(request.form.get("sets"))
        entry.reps = _parse_int(request.form.get("reps"))
        entry.weight_lbs = _parse_float(request.form.get("weight_lbs"))
    elif exercise_type == "hang":
        entry.sets = _parse_int(request.form.get("sets"))
        entry.hang_seconds = _parse_int(request.form.get("hang_seconds"))
        entry.rest_seconds = _parse_int(request.form.get("rest_seconds"))
    else:
        entry.duration_min = _parse_int(request.form.get("duration_min"))
        entry.calories_burned = _parse_int(request.form.get("calories_burned"))

    db.session.commit()
    flash("Updated.", "success")
    return redirect(url_for("exercise.index"))


@exercise_bp.route("/<int:entry_id>/delete", methods=["POST"])
def delete(entry_id):
    entry = ExerciseEntry.query.filter_by(id=entry_id, user_id=_current_user_id()).first_or_404()
    db.session.delete(entry)
    db.session.commit()
    flash("Deleted.", "success")
    return redirect(url_for("exercise.index"))


def _safe_next():
    """Redirect target for new() — allowlisted to avoid an open redirect via `next`."""
    next_url = request.form.get("next")
    if next_url in (url_for("index"), url_for("exercise.index")):
        return next_url
    return url_for("exercise.index")


def _parse_int(raw):
    if raw is None or raw.strip() == "":
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _parse_float(raw):
    if raw is None or raw.strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_date(raw):
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None
