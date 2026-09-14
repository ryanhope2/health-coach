from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from ..extensions import db
from ..models import (GOAL_TYPES, BodyStat, Goal, Measurement, User)

goals_bp = Blueprint("goals", __name__, url_prefix="/goals")


def _current_user_id():
    return session["user_id"]


def _latest_value(user_id, goal_type):
    """Latest logged value for a goal_type, to show progress."""
    if goal_type == "weight":
        row = (BodyStat.query.filter_by(user_id=user_id).filter(BodyStat.weight_lbs.isnot(None))
               .order_by(BodyStat.date.desc()).first())
        return row.weight_lbs if row else None
    if goal_type == "body_fat_pct":
        row = (BodyStat.query.filter_by(user_id=user_id).filter(BodyStat.body_fat_pct.isnot(None))
               .order_by(BodyStat.date.desc()).first())
        return row.body_fat_pct if row else None
    row = (Measurement.query.filter_by(user_id=user_id, metric=goal_type)
           .order_by(Measurement.date.desc()).first())
    return row.value_in if row else None


@goals_bp.route("/")
def index():
    user = User.query.get(_current_user_id())
    goals = Goal.query.filter_by(user_id=user.id).order_by(Goal.is_active.desc(), Goal.created_at.desc()).all()
    for g in goals:
        g.current_value = _latest_value(user.id, g.goal_type)
    return render_template("goals/index.html", user=user, goals=goals, goal_types=GOAL_TYPES)


@goals_bp.route("/new", methods=["POST"])
def new():
    user_id = _current_user_id()
    goal_type = request.form.get("goal_type")
    if goal_type not in GOAL_TYPES:
        flash("Unknown goal type.", "error")
        return redirect(url_for("goals.index"))

    target_value = _parse_float(request.form.get("target_value"))
    if target_value is None:
        flash("Enter a target value.", "error")
        return redirect(url_for("goals.index"))

    target_date = _parse_date(request.form.get("target_date"))
    starting_value = _latest_value(user_id, goal_type)

    db.session.add(Goal(
        user_id=user_id, goal_type=goal_type, target_value=target_value,
        starting_value=starting_value, target_date=target_date, is_active=True,
    ))
    db.session.commit()
    flash("Goal added.", "success")
    return redirect(url_for("goals.index"))


@goals_bp.route("/<int:goal_id>/achieve", methods=["POST"])
def achieve(goal_id):
    goal = Goal.query.filter_by(id=goal_id, user_id=_current_user_id()).first_or_404()
    goal.is_active = False
    goal.achieved_at = datetime.utcnow()
    db.session.commit()
    flash("Nice work — goal marked achieved.", "success")
    return redirect(url_for("goals.index"))


@goals_bp.route("/<int:goal_id>/delete", methods=["POST"])
def delete(goal_id):
    goal = Goal.query.filter_by(id=goal_id, user_id=_current_user_id()).first_or_404()
    db.session.delete(goal)
    db.session.commit()
    flash("Deleted.", "success")
    return redirect(url_for("goals.index"))


@goals_bp.route("/targets", methods=["POST"])
def update_targets():
    user = User.query.get(_current_user_id())
    user.daily_calorie_target = _parse_int(request.form.get("daily_calorie_target"))
    user.daily_protein_target_g = _parse_float(request.form.get("daily_protein_target_g"))
    db.session.commit()
    flash("Targets updated.", "success")
    return redirect(url_for("goals.index"))


@goals_bp.route("/period", methods=["POST"])
def update_period():
    user = User.query.get(_current_user_id())
    user.tracking_period_start = _parse_date(request.form.get("tracking_period_start"))
    db.session.commit()
    flash("Tracking period updated.", "success")
    return redirect(url_for("goals.index"))


def _parse_float(raw):
    if raw is None or raw.strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_int(raw):
    val = _parse_float(raw)
    return round(val) if val is not None else None


def _parse_date(raw):
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None
