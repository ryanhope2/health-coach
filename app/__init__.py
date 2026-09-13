import os
from datetime import date, timedelta

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
        from .models import BodyStat, ChatMessage, ExerciseEntry, MealEntry, User

        user = User.query.get(session["user_id"])
        today = date.today()

        def latest_and_prior(field):
            latest = (
                BodyStat.query.filter_by(user_id=user.id)
                .filter(field.isnot(None))
                .order_by(BodyStat.date.desc())
                .first()
            )
            prior = None
            if latest:
                prior = (
                    BodyStat.query.filter_by(user_id=user.id)
                    .filter(field.isnot(None), BodyStat.date < latest.date)
                    .order_by(BodyStat.date.desc())
                    .first()
                )
            return latest, prior

        def trend(latest_val, prior_val):
            if latest_val is None or prior_val is None:
                return None
            diff = float(latest_val) - float(prior_val)
            if diff == 0:
                return None
            return {
                "abs": abs(diff),
                "direction": "up" if diff > 0 else "down",
                "css": "text-danger" if diff > 0 else "text-success",
            }

        latest_weight, prior_weight = latest_and_prior(BodyStat.weight_lbs)
        latest_bf, prior_bf = latest_and_prior(BodyStat.body_fat_pct)
        weight_trend = trend(
            latest_weight.weight_lbs if latest_weight else None,
            prior_weight.weight_lbs if prior_weight else None,
        )
        bf_trend = trend(
            latest_bf.body_fat_pct if latest_bf else None,
            prior_bf.body_fat_pct if prior_bf else None,
        )

        todays_meals = (
            MealEntry.query.filter_by(user_id=user.id, status="confirmed")
            .filter(MealEntry.logged_at >= today)
            .all()
        )
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
        )

    return app
