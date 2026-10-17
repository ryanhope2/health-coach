"""
Blood pressure math for the /bp/ trends page, the CSV export, and the coach's context.

The point of tracking here is a before/after comparison around medication changes: a
baseline before a change, then the same numbers once the new regimen has settled in. So
readings are grouped into *segments* — one per regimen, starting at each MedicationChange
— rather than judged against categories. Morning and evening are split because dose timing
usually shows up there.

The pure functions work on Reading/Change records in local (Eastern) time; load() turns DB
rows into those. Nothing here reads the clock — callers pass `as_of`.
"""
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .progress import week_start
from .timeutils import USER_TIMEZONE, to_local_time

BASELINE_LABEL = "Baseline"
BASELINE_TARGET_DAYS = 7      # the usual home protocol: a week of morning + evening readings
DEFAULT_SETTLE_DAYS = 7       # readings this soon after a change don't count toward its average
EVENING_FROM_HOUR = 12        # readings at/after noon local count as "evening"


@dataclass
class Reading:
    at: datetime              # aware, USER_TIMEZONE
    systolic: int
    diastolic: int
    pulse: int | None = None
    notes: str | None = None
    id: int | None = None


@dataclass
class Change:
    at: datetime              # aware, USER_TIMEZONE; midnight when no time was given
    description: str
    notes: str | None = None
    has_time: bool = False
    id: int | None = None


# --- parsing ------------------------------------------------------------------------------

def parse_bp_text(text):
    """'128/82 64', '128 over 82 pulse 64', 'BP 131 / 84, heart rate 70' -> {systolic,
    diastolic, pulse}; None unless the first two numbers are a plausible reading. Typed or
    dropped in by phone dictation, same idea as the dashboard's quick weight field."""
    nums = [int(n) for n in re.findall(r"\d{2,3}", text or "")]
    if len(nums) < 2:
        return None
    sys_, dia = nums[0], nums[1]
    pulse = nums[2] if len(nums) > 2 else None
    if not (70 <= sys_ <= 260 and 40 <= dia <= 150 and sys_ > dia):
        return None
    if pulse is not None and not 30 <= pulse <= 220:
        return None
    return {"systolic": sys_, "diastolic": dia, "pulse": pulse}


# --- summaries ----------------------------------------------------------------------------

def is_evening(reading):
    return reading.at.hour >= EVENING_FROM_HOUR


def _avg(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values)) if values else None


def _part(readings):
    return {"n": len(readings),
            "systolic": _avg([x.systolic for x in readings]),
            "diastolic": _avg([x.diastolic for x in readings])}


def summarize(readings):
    """Averages (rounded to whole mmHg / bpm) overall and split morning vs. evening."""
    return {
        **_part(readings),
        "pulse": _avg([x.pulse for x in readings]),
        "am": _part([x for x in readings if not is_evening(x)]),
        "pm": _part([x for x in readings if is_evening(x)]),
        "days": len({x.at.date() for x in readings}),
    }


def baseline_progress(readings):
    """How close the readings are to a solid baseline: BASELINE_TARGET_DAYS days that each
    have a morning and an evening reading."""
    mornings = {x.at.date() for x in readings if not is_evening(x)}
    evenings = {x.at.date() for x in readings if is_evening(x)}
    complete = len(mornings & evenings)
    return {"complete_days": complete, "mornings": len(mornings), "evenings": len(evenings),
            "target": BASELINE_TARGET_DAYS, "done": complete >= BASELINE_TARGET_DAYS}


# --- regimens -----------------------------------------------------------------------------

def regimen_label(when, changes):
    """The regimen in effect at `when`: the latest change at or before it, else Baseline."""
    label = BASELINE_LABEL
    for c in sorted(changes, key=lambda c: c.at):
        if c.at <= when:
            label = c.description
    return label


def segments(readings, changes, settle_days=DEFAULT_SETTLE_DAYS):
    """One entry per regimen, oldest first. `readings` is everything taken under it;
    `stats` only counts readings from `counts_from` on (settle_days after the change — the
    baseline counts from the start), and `delta` compares those stats to the previous
    regimen's."""
    changes = sorted(changes, key=lambda c: c.at)
    bounds = [(None, BASELINE_LABEL, None)] + [(c.at, c.description, c) for c in changes]
    out = []
    for i, (start, label, chg) in enumerate(bounds):
        end = bounds[i + 1][0] if i + 1 < len(bounds) else None
        mine = [x for x in readings if (start is None or x.at >= start) and (end is None or x.at < end)]
        count_from = start + timedelta(days=settle_days) if start is not None else None
        counted = [x for x in mine if count_from is None or x.at >= count_from]
        stats = summarize(counted)
        prev = out[-1]["stats"] if out else None
        delta = None
        if prev and prev["n"] and stats["n"]:
            delta = {"systolic": stats["systolic"] - prev["systolic"],
                     "diastolic": stats["diastolic"] - prev["diastolic"]}
        out.append({"label": label, "change": chg, "start": start, "end": end,
                    "readings": mine, "counts_from": count_from.date() if count_from else None,
                    "stats": stats, "delta": delta})
    return out


# --- weeks --------------------------------------------------------------------------------

def weeks(readings, changes, as_of):
    """Sun-Sat weeks from the first reading's week through as_of's, newest first. Each has
    its stats, the med changes made that week, and the days that have readings."""
    if not readings:
        return []
    first = week_start(min(x.at.date() for x in readings))
    out = []
    wk = week_start(as_of)
    while wk >= first:
        last = wk + timedelta(days=6)
        mine = sorted((x for x in readings if wk <= x.at.date() <= last), key=lambda x: x.at)
        by_day = {}
        for x in mine:
            by_day.setdefault(x.at.date(), []).append(x)
        out.append({
            "start": wk, "end": last, "in_progress": wk <= as_of <= last,
            "stats": summarize(mine),
            "changes": [c for c in sorted(changes, key=lambda c: c.at) if wk <= c.at.date() <= last],
            "days": [{"date": d, "readings": rs} for d, rs in sorted(by_day.items())],
        })
        wk -= timedelta(days=7)
    return out


# --- chart --------------------------------------------------------------------------------

def chart_data(readings, changes):
    """Points for Chart.js, x = days (fractional) since midnight of the first reading's day."""
    if not readings:
        return None
    origin = datetime.combine(min(x.at.date() for x in readings), time(), tzinfo=USER_TIMEZONE)

    def x_of(dt):
        return round((dt - origin).total_seconds() / 86400, 3)

    def pts(rs, attr):
        return [[x_of(x.at), getattr(x, attr)] for x in rs]

    am = [x for x in readings if not is_evening(x)]
    pm = [x for x in readings if is_evening(x)]
    days = sorted({x.at.date() for x in readings})
    rolling_sys, rolling_dia = [], []
    for d in days:
        window = [x for x in readings if d - timedelta(days=6) <= x.at.date() <= d]
        noon = x_of(datetime.combine(d, time(12), tzinfo=USER_TIMEZONE))
        rolling_sys.append([noon, _avg([x.systolic for x in window])])
        rolling_dia.append([noon, _avg([x.diastolic for x in window])])
    end = max(x_of(x.at) for x in readings)
    return {
        "start": origin.date().isoformat(),
        "total_days": max(1, int(end) + 1),
        "am_sys": pts(am, "systolic"), "am_dia": pts(am, "diastolic"),
        "pm_sys": pts(pm, "systolic"), "pm_dia": pts(pm, "diastolic"),
        "rolling_sys": rolling_sys, "rolling_dia": rolling_dia,
        "changes": [{"x": x_of(c.at), "label": c.description} for c in changes if c.at >= origin],
    }


# --- DB -----------------------------------------------------------------------------------

def to_reading(row):
    return Reading(at=to_local_time(row.taken_at), systolic=row.systolic, diastolic=row.diastolic,
                   pulse=row.pulse, notes=row.notes, id=row.id)


def to_change(row):
    return Change(at=datetime.combine(row.date, row.time or time(), tzinfo=USER_TIMEZONE),
                  description=row.description, notes=row.notes, has_time=row.time is not None, id=row.id)


def load(user_id, since: date | None = None):
    """(readings oldest first, all med changes oldest first) for a user. `since` limits the
    readings only — a change before the window still decides the regimen inside it."""
    from .models import BloodPressureReading, MedicationChange
    rows = (BloodPressureReading.query.filter_by(user_id=user_id)
            .order_by(BloodPressureReading.taken_at.asc()).all())
    readings = [to_reading(x) for x in rows]
    if since is not None:
        readings = [x for x in readings if x.at.date() >= since]
    changes = [to_change(c) for c in
               MedicationChange.query.filter_by(user_id=user_id)
               .order_by(MedicationChange.date.asc(), MedicationChange.time.asc()).all()]
    return readings, changes
