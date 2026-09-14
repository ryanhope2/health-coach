import os
from datetime import datetime, timedelta

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from .blueprints.body import body_bp
from .blueprints.coach import coach_bp
from .blueprints.exercise import exercise_bp
from .blueprints.goals import goals_bp
from .blueprints.meals import meals_bp
from .extensions import db


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)

    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        SQLALCHEMY_DATABASE_URI="sqlite:///" + os.path.join(app.instance_path, "moronfitness.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        ANTHROPIC_API_KEY=os.environ.get("ANTHROPIC_API_KEY"),
        APP_BASE_URL=os.environ.get("APP_BASE_URL", "https://moron.bigpour.app"),
        PHOTO_RETENTION_DAYS=int(os.environ.get("PHOTO_RETENTION_DAYS", "30")),
    )

    if config:
        app.config.from_mapping(config)

    try:
        app.config.from_pyfile("config.py")
    except FileNotFoundError:
        pass

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(os.path.join(app.instance_path, "photos", "meals"), exist_ok=True)

    db.init_app(app)

    from .models import GOAL_TYPE_LABELS
    app.jinja_env.filters["goal_label"] = lambda t: GOAL_TYPE_LABELS.get(t, t.replace("_", " ").capitalize())

    app.register_blueprint(body_bp)
    app.register_blueprint(meals_bp)
    app.register_blueprint(exercise_bp)
    app.register_blueprint(goals_bp)
    app.register_blueprint(coach_bp)

    @app.before_request
    def require_login():
        public = ("login", "static")
        if request.endpoint in public:
            return
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        from .models import User

        error = None
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = User.query.filter_by(username=username).first()
            if user and check_password_hash(user.password_hash, password):
                session.permanent = True
                session["user_id"] = user.id
                return redirect(request.args.get("next") or url_for("index"))
            error = "Invalid credentials."
        return render_template("login.html", error=error)

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    def index():
        from .models import BodyStat, ChatMessage, ExerciseEntry, MealEntry, SavedMeal, User
        from .timeutils import local_today, to_local_date

        user = User.query.get(session["user_id"])
        today = local_today()

        def latest_stat(field):
            return (
                BodyStat.query.filter_by(user_id=user.id)
                .filter(field.isnot(None))
                .order_by(BodyStat.date.desc())
                .first()
            )

        def period_baseline(field):
            """Average of readings in the first 7 days of user.tracking_period_start.
            Returns None if no period is set or no readings fall in that window."""
            if not user.tracking_period_start:
                return None
            from datetime import timedelta
            window_end = user.tracking_period_start + timedelta(days=6)
            rows = (
                BodyStat.query.filter_by(user_id=user.id)
                .filter(field.isnot(None),
                        BodyStat.date >= user.tracking_period_start,
                        BodyStat.date <= window_end)
                .all()
            )
            if not rows:
                return None
            return sum(float(getattr(r, field.key)) for r in rows) / len(rows)

        def prior_entry_val(field, latest_row):
            """Fallback: value from the most recent entry before the latest one."""
            if not latest_row:
                return None
            prior = (
                BodyStat.query.filter_by(user_id=user.id)
                .filter(field.isnot(None), BodyStat.date < latest_row.date)
                .order_by(BodyStat.date.desc())
                .first()
            )
            return float(getattr(prior, field.key)) if prior else None

        def trend(latest_val, baseline_val):
            if latest_val is None or baseline_val is None:
                return None
            diff = float(latest_val) - float(baseline_val)
            if diff == 0:
                return None
            return {
                "abs": abs(diff),
                "direction": "up" if diff > 0 else "down",
                "css": "text-danger" if diff > 0 else "text-success",
            }

        latest_weight = latest_stat(BodyStat.weight_lbs)
        latest_bf = latest_stat(BodyStat.body_fat_pct)

        weight_baseline = period_baseline(BodyStat.weight_lbs) or prior_entry_val(BodyStat.weight_lbs, latest_weight)
        bf_baseline = period_baseline(BodyStat.body_fat_pct) or prior_entry_val(BodyStat.body_fat_pct, latest_bf)

        weight_trend = trend(
            float(latest_weight.weight_lbs) if latest_weight else None,
            weight_baseline,
        )
        bf_trend = trend(
            float(latest_bf.body_fat_pct) if latest_bf else None,
            bf_baseline,
        )

        # logged_at is stored as an absolute UTC instant; a loose UTC-day bound narrows
        # the query, then to_local_date() does the actual (timezone-correct) day check —
        # SQLite's func.date() would truncate the raw UTC value instead of the local day.
        # The bound must be full datetimes, not bare dates: comparing a DateTime column
        # against a plain date string in SQLite is a lexicographic string comparison, so
        # e.g. "2026-09-14 02:00:00" <= "2026-09-14" is FALSE (the longer string sorts
        # after its own prefix) — that upper bound would silently exclude everything
        # after exact midnight on the boundary date.
        loose_lower = datetime.combine(today - timedelta(days=1), datetime.min.time())
        loose_upper = datetime.combine(today + timedelta(days=2), datetime.min.time())
        todays_meals = [
            m for m in
            MealEntry.query.filter_by(user_id=user.id, status="confirmed")
            .filter(MealEntry.logged_at >= loose_lower, MealEntry.logged_at < loose_upper)
            .all()
            if to_local_date(m.logged_at) == today
        ]
        today_calories = sum(m.calories or 0 for m in todays_meals)
        today_protein = sum(float(m.protein_g or 0) for m in todays_meals)

        # Exercise this week: fixed Sunday-through-Saturday calendar week, not a
        # rolling trailing-7-days window.
        days_since_sunday = (today.weekday() + 1) % 7
        week_start = today - timedelta(days=days_since_sunday)
        week_dates = [week_start + timedelta(days=i) for i in range(7)]
        exercised_dates = {
            e.date for e in
            ExerciseEntry.query.filter_by(user_id=user.id)
            .filter(ExerciseEntry.date >= week_start, ExerciseEntry.date <= week_dates[-1])
            .all()
        }
        exercise_days = [{"date": d, "done": d in exercised_dates} for d in week_dates]
        exercise_count = sum(1 for d in exercise_days if d["done"])
        if exercise_count >= 4:
            exercise_color = "green"
        elif exercise_count >= 2:
            exercise_color = "yellow"
        elif exercise_count >= 1:
            exercise_color = "red"
        else:
            exercise_color = None

        recent_chat = (
            ChatMessage.query.filter_by(user_id=user.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(6)
            .all()
        )
        recent_chat.reverse()

        saved_drinks = (
            SavedMeal.query.filter_by(user_id=user.id, meal_type="alcohol")
            .order_by(SavedMeal.last_used_at.desc(), SavedMeal.created_at.desc())
            .all()
        )

        return render_template(
            "index.html",
            user=user,
            latest_weight=latest_weight,
            weight_trend=weight_trend,
            latest_bf=latest_bf,
            bf_trend=bf_trend,
            today_calories=today_calories,
            today_protein=today_protein,
            exercise_days=exercise_days,
            exercise_color=exercise_color,
            messages=recent_chat,
            today=today.isoformat(),
            saved_drinks=saved_drinks,
        )

    return app
