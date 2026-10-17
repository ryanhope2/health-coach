"""Blood pressure: log readings, mark medication changes, the /bp/ trends page, CSV export.
The math lives in app/bp_trends.py."""
import csv
import io
from datetime import datetime, timedelta

from flask import Blueprint, Response, flash, redirect, render_template, request, session, url_for

from .. import bp_trends
from ..extensions import db
from ..models import BloodPressureReading, MedicationChange
from ..timeutils import local_now, local_to_utc, local_today

bp_bp = Blueprint("bp", __name__, url_prefix="/bp")

RANGES = {"30": 30, "90": 90}   # ?days=…; anything else means all readings
RECENT_READINGS = 10


def _current_user_id():
    return session["user_id"]


def _range_args():
    days = request.args.get("days")
    return (days, local_today() - timedelta(days=RANGES[days])) if days in RANGES else (None, None)


def _settle_days():
    try:
        return max(0, min(30, int(request.args.get("settle", bp_trends.DEFAULT_SETTLE_DAYS))))
    except ValueError:
        return bp_trends.DEFAULT_SETTLE_DAYS


def recent_readings(user_id):
    rows = (BloodPressureReading.query.filter_by(user_id=user_id)
            .order_by(BloodPressureReading.taken_at.desc()).limit(RECENT_READINGS).all())
    return [bp_trends.to_reading(r) for r in rows]


@bp_bp.route("/")
def index():
    user_id = _current_user_id()
    days, since = _range_args()
    settle = _settle_days()
    readings, changes = bp_trends.load(user_id)
    # Regimen comparisons always use every reading; the range only narrows the chart and weeks.
    segs = bp_trends.segments(readings, changes, settle)
    shown = [r for r in readings if since is None or r.at.date() >= since]
    return render_template(
        "bp/index.html",
        has_readings=bool(readings),
        segments=list(reversed(segs)),
        baseline=bp_trends.baseline_progress(segs[0]["readings"]) if not changes else None,
        baseline_stats=segs[0]["stats"],
        changes=list(reversed(changes)),
        weeks=bp_trends.weeks(shown, changes, local_today()) if shown else [],
        chart=bp_trends.chart_data(shown, changes),
        recent=recent_readings(user_id),
        days=days, settle=settle,
        today=local_today().isoformat(), now=local_now().strftime("%H:%M"),
    )


# --- readings -----------------------------------------------------------------------------

@bp_bp.route("/reading", methods=["POST"])
def add_reading():
    f = request.form
    # A dictated "128 over 82 pulse 64" can land whole in the first field; the page's JS
    # splits it on blur, and this catches it if JS didn't run.
    sys_, dia, pulse = ((f.get(k) or "").strip() for k in ("systolic", "diastolic", "pulse"))
    parsed = bp_trends.parse_bp_text(sys_ if not dia else f"{sys_} / {dia} {pulse}")
    if parsed is None:
        flash("Enter a reading like 128 / 82 (pulse optional).", "error")
        return redirect(_safe_next())

    d = _parse_date(f.get("date")) or local_today()
    t = _parse_time(f.get("time")) or local_now().time()
    db.session.add(BloodPressureReading(
        user_id=_current_user_id(), taken_at=local_to_utc(d, t),
        systolic=parsed["systolic"], diastolic=parsed["diastolic"], pulse=parsed["pulse"],
        notes=(f.get("notes") or "").strip() or None,
    ))
    db.session.commit()
    flash(f"Logged {parsed['systolic']}/{parsed['diastolic']}.", "success")
    return redirect(_safe_next())


def _safe_next():
    """Redirect target for add_reading — allowlisted to avoid an open redirect via `next`."""
    next_url = request.form.get("next")
    if next_url in (url_for("body.index"), url_for("bp.index")):
        return next_url
    return url_for("bp.index")


@bp_bp.route("/reading/<int:reading_id>/delete", methods=["POST"])
def delete_reading(reading_id):
    r = BloodPressureReading.query.filter_by(id=reading_id, user_id=_current_user_id()).first_or_404()
    db.session.delete(r)
    db.session.commit()
    flash("Deleted.", "success")
    return redirect(_safe_next())


# --- medication changes -------------------------------------------------------------------

def _apply_med_change_form(change):
    """Fill a MedicationChange from the form; False (and a flash) if date/description missing."""
    d = _parse_date(request.form.get("date"))
    description = (request.form.get("description") or "").strip()
    if d is None or not description:
        flash("A med change needs a date and what changed.", "error")
        return False
    change.date = d
    change.time = _parse_time(request.form.get("time"))
    change.description = description[:200]
    change.notes = (request.form.get("notes") or "").strip() or None
    return True


@bp_bp.route("/med-change", methods=["POST"])
def add_med_change():
    change = MedicationChange(user_id=_current_user_id())
    if _apply_med_change_form(change):
        db.session.add(change)
        db.session.commit()
        flash("Med change saved.", "success")
    return redirect(url_for("bp.index"))


@bp_bp.route("/med-change/<int:change_id>/update", methods=["POST"])
def update_med_change(change_id):
    change = MedicationChange.query.filter_by(id=change_id, user_id=_current_user_id()).first_or_404()
    if _apply_med_change_form(change):
        db.session.commit()
        flash("Med change updated.", "success")
    else:
        db.session.rollback()
    return redirect(url_for("bp.index"))


@bp_bp.route("/med-change/<int:change_id>/delete", methods=["POST"])
def delete_med_change(change_id):
    change = MedicationChange.query.filter_by(id=change_id, user_id=_current_user_id()).first_or_404()
    db.session.delete(change)
    db.session.commit()
    flash("Deleted.", "success")
    return redirect(url_for("bp.index"))


# --- CSV ----------------------------------------------------------------------------------

@bp_bp.route("/export.csv")
def export_csv():
    """Readings (local time, oldest first, each tagged with the regimen in effect), then a
    "Medication changes" section listing every change with its date and notes."""
    _, since = _range_args()
    readings, changes = bp_trends.load(_current_user_id(), since=since)
    out = io.StringIO()
    out.write("﻿")  # BOM, so Excel reads the UTF-8 (e.g. "5 → 10 mg") correctly
    w = csv.writer(out)
    w.writerow(["date", "time", "systolic", "diastolic", "pulse", "regimen", "notes"])
    for r in readings:
        w.writerow([r.at.date().isoformat(), r.at.strftime("%H:%M"), r.systolic, r.diastolic,
                    "" if r.pulse is None else r.pulse, bp_trends.regimen_label(r.at, changes), r.notes or ""])
    w.writerow([])
    w.writerow(["Medication changes"])
    w.writerow(["date", "time", "change", "notes"])
    for c in changes:
        w.writerow([c.at.date().isoformat(), c.at.strftime("%H:%M") if c.has_time else "",
                    c.description, c.notes or ""])
    filename = f"blood-pressure-{local_today().isoformat()}.csv"
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _parse_date(raw):
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date() if raw else None
    except ValueError:
        return None


def _parse_time(raw):
    try:
        return datetime.strptime(raw, "%H:%M").time() if raw else None
    except ValueError:
        return None
