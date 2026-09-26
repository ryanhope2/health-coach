from datetime import datetime, timedelta

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from .. import progress
from ..models import Goal, User, WeeklyRecap
from ..recap import generate_recap
from ..timeutils import local_today

progress_bp = Blueprint("progress", __name__, url_prefix="/progress")


@progress_bp.route("/")
def index():
    user = User.query.get(session["user_id"])
    period = user.current_period()
    if period is None:
        return render_template("progress/index.html", period=None)

    today = local_today()
    as_of = min(today, period.end_date + timedelta(days=1))
    weeks = progress.period_weeks(user.id, period, as_of)
    this_week = weeks[0] if weeks and weeks[0]["in_progress"] else None
    goal = Goal.query.filter_by(user_id=user.id, period_id=period.id, goal_type="weight", is_active=True).first()

    recaps = (WeeklyRecap.query.filter_by(user_id=user.id)
              .filter(WeeklyRecap.week_start >= progress.week_start(period.start_date),
                      WeeklyRecap.week_start <= period.end_date)
              .order_by(WeeklyRecap.week_start.desc()).all())
    last_finished_week = progress.week_start(today) - timedelta(days=7)

    return render_template(
        "progress/index.html",
        period=period,
        position=progress.period_position(period, today),
        elapsed_pct=min(100, max(0, round(100 * (today - period.start_date).days
                                          / max((period.end_date - period.start_date).days, 1)))),
        weight=progress.weight_progress(user.id, period, goal, as_of),
        this_week=this_week,
        weeks=weeks,
        today=today,
        calorie_cap=progress.calorie_cap(period),
        recap=recaps[0] if recaps else None,
        recap_partial=bool(recaps) and recaps[0].covers_through < recaps[0].week_start + timedelta(days=6),
        older_recaps=recaps[1:],
        current_week_start=progress.week_start(today) if this_week else None,
        last_finished_week=last_finished_week if last_finished_week + timedelta(days=6) >= period.start_date else None,
    )


@progress_bp.route("/recap", methods=["POST"])
def recap():
    """Write or rewrite the recap for one week (the Refresh / "this week so far" buttons)."""
    user = User.query.get(session["user_id"])
    period = user.current_period()
    try:
        wk_start = progress.week_start(datetime.strptime(request.form["week_start"], "%Y-%m-%d").date())
    except (KeyError, ValueError):
        wk_start = None
    if period is None or wk_start is None or wk_start > local_today():
        flash("Couldn't tell which week to recap.", "error")
        return redirect(url_for("progress.index"))
    try:
        generate_recap(current_app.config["ANTHROPIC_API_KEY"], user, period, wk_start)
    except Exception as e:
        current_app.logger.exception("recap generation failed")
        flash(f"Couldn't write the recap ({e}).", "error")
    return redirect(url_for("progress.index"))
