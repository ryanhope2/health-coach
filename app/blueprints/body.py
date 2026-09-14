from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from ..extensions import db
from ..models import MEASUREMENT_METRICS, BodyStat, Measurement
from ..timeutils import local_today

body_bp = Blueprint("body", __name__, url_prefix="/body")


def _current_user_id():
    return session["user_id"]


@body_bp.route("/")
def index():
    user_id = _current_user_id()
    stats = BodyStat.query.filter_by(user_id=user_id).order_by(BodyStat.date.desc()).limit(90).all()
    measurements = Measurement.query.filter_by(user_id=user_id).order_by(Measurement.date.desc()).limit(90).all()
    measurements_by_metric = {}
    for m in measurements:
        measurements_by_metric.setdefault(m.metric, []).append(m)
    return render_template(
        "body/index.html",
        stats=stats,
        measurements_by_metric=measurements_by_metric,
        metrics=MEASUREMENT_METRICS,
        today=local_today().isoformat(),
    )


@body_bp.route("/stat", methods=["POST"])
def add_stat():
    user_id = _current_user_id()
    entry_date = _parse_date(request.form.get("date")) or local_today()
    weight = _parse_float(request.form.get("weight_lbs"))
    body_fat = _parse_float(request.form.get("body_fat_pct"))
    notes = request.form.get("notes", "").strip() or None

    if weight is None and body_fat is None:
        flash("Enter a weight and/or body fat % to log an entry.", "error")
        return redirect(_safe_next())

    existing = BodyStat.query.filter_by(user_id=user_id, date=entry_date).first()
    if existing:
        if weight is not None:
            existing.weight_lbs = weight
        if body_fat is not None:
            existing.body_fat_pct = body_fat
        if notes:
            existing.notes = notes
    else:
        db.session.add(BodyStat(
            user_id=user_id, date=entry_date, weight_lbs=weight,
            body_fat_pct=body_fat, notes=notes,
        ))
    db.session.commit()
    flash("Logged.", "success")
    return redirect(_safe_next())


def _safe_next():
    """Redirect target for add_stat — allowlisted to avoid an open redirect via `next`."""
    next_url = request.form.get("next")
    if next_url in (url_for("index"), url_for("body.index")):
        return next_url
    return url_for("body.index")


@body_bp.route("/stat/<int:stat_id>/delete", methods=["POST"])
def delete_stat(stat_id):
    stat = BodyStat.query.filter_by(id=stat_id, user_id=_current_user_id()).first_or_404()
    db.session.delete(stat)
    db.session.commit()
    flash("Deleted.", "success")
    return redirect(url_for("body.index"))


@body_bp.route("/measurement", methods=["POST"])
def add_measurement():
    user_id = _current_user_id()
    metric = request.form.get("metric")
    if metric not in MEASUREMENT_METRICS:
        flash("Unknown measurement type.", "error")
        return redirect(url_for("body.index"))

    value = _parse_float(request.form.get("value_in"))
    if value is None:
        flash("Enter a value.", "error")
        return redirect(url_for("body.index"))

    entry_date = _parse_date(request.form.get("date")) or local_today()
    notes = request.form.get("notes", "").strip() or None

    db.session.add(Measurement(
        user_id=user_id, date=entry_date, metric=metric,
        value_in=value, notes=notes,
    ))
    db.session.commit()
    flash("Logged.", "success")
    return redirect(url_for("body.index"))


@body_bp.route("/measurement/<int:measurement_id>/delete", methods=["POST"])
def delete_measurement(measurement_id):
    m = Measurement.query.filter_by(id=measurement_id, user_id=_current_user_id()).first_or_404()
    db.session.delete(m)
    db.session.commit()
    flash("Deleted.", "success")
    return redirect(url_for("body.index"))


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
