import uuid
from datetime import datetime, timedelta
from pathlib import Path

from flask import (Blueprint, current_app, flash, jsonify, redirect, render_template,
                    request, send_file, session, url_for)

from ..extensions import db
from ..meal_ai import parse_meal
from ..models import FoodItem, MealEntry, SavedMeal
from ..timeutils import local_date_to_utc_noon, local_today, to_local_date

meals_bp = Blueprint("meals", __name__, url_prefix="/meals")

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

PAGE_DAYS = 7
MEAL_TYPE_ORDER = ["breakfast", "lunch", "dinner", "snack", "alcohol"]
MEAL_TYPE_LABELS = {
    "breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snack",
    "alcohol": "Alcohol",
}


def _current_user_id():
    return session["user_id"]


def _meal_type_sort_key(meal_type):
    try:
        return MEAL_TYPE_ORDER.index(meal_type)
    except ValueError:
        return len(MEAL_TYPE_ORDER)


def _meal_type_label(meal_type):
    return MEAL_TYPE_LABELS.get(meal_type, "Other")


def _day_label(day, today, yesterday):
    if day == today:
        return "Today"
    if day == yesterday:
        return "Yesterday"
    return day.strftime("%A, %B %-d")


def _parse_logged_date(date_str):
    """Convert a YYYY-MM-DD string to a naive-UTC datetime suitable for logged_at.
    Today → utcnow() (preserve natural entry order within the day).
    Any other date → noon Eastern on that day (safe mid-day anchor, no UTC-offset risk).
    Missing/invalid → None (caller skips the assignment, letting the model default fire)."""
    if not date_str:
        return None
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None
    if d == local_today():
        return datetime.utcnow()
    return local_date_to_utc_noon(d)


@meals_bp.route("/")
def index():
    user_id = _current_user_id()
    today = local_today()

    pending_meals = (
        MealEntry.query.filter_by(user_id=user_id, status="pending")
        .order_by(MealEntry.logged_at.desc())
        .all()
    )

    # logged_at is stored as an absolute UTC instant. SQLite has no timezone-aware date
    # truncation, so day-grouping happens here in Python via to_local_date() rather than
    # func.date() in SQL — func.date() would truncate the raw UTC value, landing a meal
    # logged near midnight Eastern on the wrong calendar day.
    confirmed = (
        MealEntry.query.filter_by(user_id=user_id, status="confirmed")
        .order_by(MealEntry.logged_at.asc())
        .all()
    )
    by_day = {}
    for e in confirmed:
        by_day.setdefault(to_local_date(e.logged_at), []).append(e)

    todays_confirmed = by_day.get(today, [])
    today_calories = sum(m.calories or 0 for m in todays_confirmed)
    today_protein = sum(float(m.protein_g or 0) for m in todays_confirmed)

    # Day-based pagination: find which calendar days (not rows) to show. `before` (a
    # YYYY-MM-DD string) pages further back in time via "Show earlier days".
    before = request.args.get("before")
    before_date = datetime.strptime(before, "%Y-%m-%d").date() if before else None
    all_days_desc = sorted(by_day.keys(), reverse=True)
    if before_date:
        all_days_desc = [d for d in all_days_desc if d < before_date]
    has_more = len(all_days_desc) > PAGE_DAYS
    shown_days = all_days_desc[:PAGE_DAYS]

    days = []
    yesterday = today - timedelta(days=1)
    for d in shown_days:
        day_entries = by_day.get(d, [])
        by_type = {}
        for e in day_entries:
            by_type.setdefault(e.meal_type, []).append(e)
        meal_groups = [
            {
                "label": _meal_type_label(mt),
                "entries": group_entries,
                "calories": sum(x.calories or 0 for x in group_entries),
                "protein": sum(float(x.protein_g or 0) for x in group_entries),
            }
            for mt, group_entries in sorted(by_type.items(), key=lambda kv: _meal_type_sort_key(kv[0]))
        ]
        days.append({
            "label": _day_label(d, today, yesterday),
            "is_today": d == today,
            "calories": sum(x.calories or 0 for x in day_entries),
            "protein": sum(float(x.protein_g or 0) for x in day_entries),
            "meal_groups": meal_groups,
        })

    # SQLite sorts NULL first ascending / last descending, so unused saved meals
    # (last_used_at is NULL) naturally fall after ones that have been used.
    all_saved = (
        SavedMeal.query.filter_by(user_id=user_id)
        .order_by(SavedMeal.last_used_at.desc(), SavedMeal.created_at.desc())
        .all()
    )
    saved_meals = [sm for sm in all_saved if sm.meal_type != "alcohol"]
    saved_drinks = [sm for sm in all_saved if sm.meal_type == "alcohol"]
    return render_template(
        "meals/index.html",
        pending_meals=pending_meals,
        days=days,
        has_more=has_more,
        next_before=shown_days[-1].isoformat() if (has_more and shown_days) else None,
        today_calories=today_calories,
        today_protein=today_protein,
        saved_meals=saved_meals,
        saved_drinks=saved_drinks,
    )


@meals_bp.route("/new", methods=["GET", "POST"])
def new():
    if request.method == "GET":
        return render_template("meals/new.html")

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def fail(message):
        if is_ajax:
            return jsonify({"error": message}), 400
        flash(message, "error")
        return render_template("meals/new.html")

    description = request.form.get("description", "").strip() or None
    meal_type = request.form.get("meal_type") or None
    logged_at = _parse_logged_date(request.form.get("logged_date"))
    photo = request.files.get("photo")

    photo_path = None
    if photo and photo.filename:
        ext = Path(photo.filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return fail("Unsupported image type.")
        photos_dir = Path(current_app.instance_path) / "photos" / "meals"
        photos_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}{ext}"
        full_path = photos_dir / filename
        photo.save(full_path)
        photo_path = str(full_path)

    if not description and not photo_path:
        return fail("Add a description or a photo (or both).")

    meal_kwargs = dict(
        user_id=_current_user_id(),
        meal_type=meal_type,
        description=description,
        photo_path=photo_path,
        status="pending",
    )
    if logged_at is not None:
        meal_kwargs["logged_at"] = logged_at
    meal = MealEntry(**meal_kwargs)
    db.session.add(meal)
    db.session.commit()

    def done(flash_message=None, flash_category="error"):
        review_url = url_for("meals.review", meal_id=meal.id)
        if is_ajax:
            return jsonify({"redirect": review_url})
        if flash_message:
            flash(flash_message, flash_category)
        return redirect(review_url)

    try:
        result = parse_meal(
            api_key=current_app.config["ANTHROPIC_API_KEY"],
            photo_path=photo_path,
            text_description=description,
        )
    except Exception as e:
        current_app.logger.exception("meal parsing failed")
        return done(f"AI parsing failed ({e}). You can still enter nutrition manually below.")

    meal.calories = round(result.get("total_calories") or 0) or None
    meal.protein_g = result.get("total_protein_g")
    meal.carbs_g = result.get("total_carbs_g")
    meal.fat_g = result.get("total_fat_g")
    meal.ai_raw_response = result.get("_raw_text")
    for item in result.get("items", []):
        db.session.add(FoodItem(
            meal_id=meal.id,
            name=item.get("name", "Item"),
            quantity=item.get("quantity"),
            calories=item.get("calories"),
            protein_g=item.get("protein_g"),
            carbs_g=item.get("carbs_g"),
            fat_g=item.get("fat_g"),
        ))
    db.session.commit()

    return done()


@meals_bp.route("/<int:meal_id>/review", methods=["GET", "POST"])
def review(meal_id):
    meal = MealEntry.query.filter_by(id=meal_id, user_id=_current_user_id()).first_or_404()

    if request.method == "POST":
        meal.meal_type = request.form.get("meal_type") or None
        meal.calories = _parse_int(request.form.get("calories"))
        meal.protein_g = _parse_float(request.form.get("protein_g"))
        meal.carbs_g = _parse_float(request.form.get("carbs_g"))
        meal.fat_g = _parse_float(request.form.get("fat_g"))
        logged_at = _parse_logged_date(request.form.get("logged_date"))
        if logged_at is not None:
            meal.logged_at = logged_at
        meal.status = "confirmed"

        if request.form.get("save_as_quick_meal") == "1":
            user_id = _current_user_id()
            name = (request.form.get("quick_meal_name", "").strip()
                    or (meal.description or "Quick meal")[:200])
            existing = (
                SavedMeal.query.filter_by(user_id=user_id)
                .filter(db.func.lower(SavedMeal.name) == name.lower())
                .first()
            )
            target = existing or SavedMeal(user_id=user_id, name=name)
            target.description = meal.description
            target.meal_type = meal.meal_type
            target.calories = meal.calories
            target.protein_g = meal.protein_g
            target.carbs_g = meal.carbs_g
            target.fat_g = meal.fat_g
            if not existing:
                db.session.add(target)
            flash_suffix = " and saved for quick re-use" if not existing else ' and updated your "%s" quick meal' % name
        else:
            flash_suffix = ""

        db.session.commit()
        flash(f"Meal logged{flash_suffix}.", "success")
        return redirect(url_for("meals.index"))

    meal_date = to_local_date(meal.logged_at)
    return render_template("meals/review.html", meal=meal, meal_date=meal_date)


@meals_bp.route("/<int:meal_id>/photo")
def photo(meal_id):
    meal = MealEntry.query.filter_by(id=meal_id, user_id=_current_user_id()).first_or_404()
    if not meal.photo_path or not Path(meal.photo_path).exists():
        return "", 404
    return send_file(meal.photo_path)


@meals_bp.route("/quick/<int:saved_meal_id>", methods=["POST"])
def quick_log(saved_meal_id):
    """Instantly log a saved meal as-is — no AI call, just reuses its stored nutrition."""
    sm = SavedMeal.query.filter_by(id=saved_meal_id, user_id=_current_user_id()).first_or_404()
    db.session.add(MealEntry(
        user_id=_current_user_id(),
        description=sm.description or sm.name,
        meal_type=request.form.get("meal_type") or sm.meal_type,
        calories=sm.calories,
        protein_g=sm.protein_g,
        carbs_g=sm.carbs_g,
        fat_g=sm.fat_g,
        status="confirmed",
    ))
    sm.last_used_at = datetime.utcnow()
    db.session.commit()
    flash(f'Logged "{sm.name}".', "success")
    return redirect(_safe_next())


def _safe_next():
    """Redirect target for quick_log — allowlisted to avoid an open redirect via `next`."""
    next_url = request.form.get("next")
    if next_url in (url_for("index"), url_for("meals.index")):
        return next_url
    return url_for("meals.index")


@meals_bp.route("/quick/<int:saved_meal_id>/delete", methods=["POST"])
def delete_saved_meal(saved_meal_id):
    sm = SavedMeal.query.filter_by(id=saved_meal_id, user_id=_current_user_id()).first_or_404()
    was_drink = sm.meal_type == "alcohol"
    db.session.delete(sm)
    db.session.commit()
    flash("Removed from quick meals.", "success")
    return redirect(url_for("meals.quick_drinks") if was_drink else url_for("meals.index"))


@meals_bp.route("/quick-drinks")
def quick_drinks():
    drinks = (
        SavedMeal.query.filter_by(user_id=_current_user_id(), meal_type="alcohol")
        .order_by(SavedMeal.created_at.asc())
        .all()
    )
    return render_template("meals/quick_drinks.html", drinks=drinks)


@meals_bp.route("/quick-drinks/new", methods=["POST"])
def add_quick_drink():
    name = request.form.get("name", "").strip()
    calories = _parse_int(request.form.get("calories"))
    if not name:
        flash("Give the drink a name.", "error")
        return redirect(url_for("meals.quick_drinks"))
    db.session.add(SavedMeal(
        user_id=_current_user_id(), name=name, meal_type="alcohol", calories=calories,
    ))
    db.session.commit()
    flash(f'Added "{name}".', "success")
    return redirect(url_for("meals.quick_drinks"))


@meals_bp.route("/quick-drinks/<int:saved_meal_id>/update", methods=["POST"])
def update_quick_drink(saved_meal_id):
    sm = SavedMeal.query.filter_by(
        id=saved_meal_id, user_id=_current_user_id(), meal_type="alcohol"
    ).first_or_404()
    name = request.form.get("name", "").strip()
    if not name:
        flash("Give the drink a name.", "error")
        return redirect(url_for("meals.quick_drinks"))
    sm.name = name
    sm.calories = _parse_int(request.form.get("calories"))
    db.session.commit()
    flash("Updated.", "success")
    return redirect(url_for("meals.quick_drinks"))


@meals_bp.route("/<int:meal_id>/delete", methods=["POST"])
def delete(meal_id):
    meal = MealEntry.query.filter_by(id=meal_id, user_id=_current_user_id()).first_or_404()
    if meal.photo_path:
        try:
            Path(meal.photo_path).unlink(missing_ok=True)
        except OSError:
            pass
    db.session.delete(meal)
    db.session.commit()
    flash("Deleted.", "success")
    return redirect(url_for("meals.index"))


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
