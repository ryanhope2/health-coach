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
        return redirect(url_for("exercise.index"))

    entry_date = _parse_date(request.form.get("date")) or local_today()
    duration = _parse_int(request.form.get("duration_min"))
    calories_burned = _parse_int(request.form.get("calories_burned"))
    notes = request.form.get("notes", "").strip() or None

    db.session.add(ExerciseEntry(
        user_id=_current_user_id(), date=entry_date, activity=activity,
        duration_min=duration, calories_burned=calories_burned, notes=notes,
    ))
    db.session.commit()
    flash("Logged.", "success")
    return redirect(url_for("exercise.index"))


@exercise_bp.route("/<int:entry_id>/delete", methods=["POST"])
def delete(entry_id):
    entry = ExerciseEntry.query.filter_by(id=entry_id, user_id=_current_user_id()).first_or_404()
    db.session.delete(entry)
    db.session.commit()
    flash("Deleted.", "success")
    return redirect(url_for("exercise.index"))


def _parse_int(raw):
    if raw is None or raw.strip() == "":
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _parse_date(raw):
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None
