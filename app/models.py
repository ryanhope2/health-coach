import re
from datetime import datetime

from .extensions import db
from .timeutils import local_today

MEASUREMENT_METRICS = ["waist", "hips", "chest", "bicep", "thigh"]
GOAL_TYPES = ["weight", "body_fat_pct"] + MEASUREMENT_METRICS
GOAL_TYPE_LABELS = {"weight": "Weight", "body_fat_pct": "Body fat %"}
for _m in MEASUREMENT_METRICS:
    GOAL_TYPE_LABELS[_m] = _m.capitalize()


def normalize_note_key(raw: str) -> str:
    """
    Turn freeform text into a stable slug, e.g. "Alcohol Strategy" -> "alcohol_strategy".
    Used both when the coach saves a note and when the user edits one by hand, so a key
    typed either way lands on the same row instead of creating a near-duplicate.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", raw.strip().lower()).strip("_")
    return slug[:50]


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(100))
    daily_calorie_target = db.Column(db.Integer, nullable=True)
    daily_protein_target_g = db.Column(db.Numeric(5, 1), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    body_stats = db.relationship("BodyStat", back_populates="user", cascade="all, delete-orphan")
    measurements = db.relationship("Measurement", back_populates="user", cascade="all, delete-orphan")
    meals = db.relationship("MealEntry", back_populates="user", cascade="all, delete-orphan")
    saved_meals = db.relationship("SavedMeal", back_populates="user", cascade="all, delete-orphan")
    exercises = db.relationship("ExerciseEntry", back_populates="user", cascade="all, delete-orphan")
    goals = db.relationship("Goal", back_populates="user", cascade="all, delete-orphan")
    chat_messages = db.relationship("ChatMessage", back_populates="user", cascade="all, delete-orphan")
    coach_notes = db.relationship("CoachNote", back_populates="user", cascade="all, delete-orphan")

    @property
    def label(self):
        return self.display_name or self.username


class BodyStat(db.Model):
    """One row per day: weight and/or body fat %."""
    __tablename__ = "body_stats"
    __table_args__ = (db.UniqueConstraint("user_id", "date", name="uq_body_stat_user_date"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    date = db.Column(db.Date, nullable=False, default=local_today)
    weight_lbs = db.Column(db.Numeric(5, 1), nullable=True)
    body_fat_pct = db.Column(db.Numeric(4, 1), nullable=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="body_stats")


class Measurement(db.Model):
    """A single body measurement (waist, bicep, etc.) on a given date."""
    __tablename__ = "measurements"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    date = db.Column(db.Date, nullable=False, default=local_today)
    metric = db.Column(db.String(20), nullable=False)  # one of MEASUREMENT_METRICS
    value_in = db.Column(db.Numeric(5, 1), nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="measurements")


class MealEntry(db.Model):
    """A logged meal — from a photo, a text description, or both."""
    __tablename__ = "meal_entries"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    logged_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    meal_type = db.Column(db.String(20))  # breakfast | lunch | dinner | snack
    description = db.Column(db.Text)
    photo_path = db.Column(db.String(500))
    calories = db.Column(db.Integer)
    protein_g = db.Column(db.Numeric(5, 1))
    carbs_g = db.Column(db.Numeric(5, 1))
    fat_g = db.Column(db.Numeric(5, 1))
    status = db.Column(db.String(20), default="pending", nullable=False)
    # status: pending (AI-parsed, awaiting confirm) | confirmed
    ai_raw_response = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="meals")
    items = db.relationship("FoodItem", back_populates="meal", cascade="all, delete-orphan")


class FoodItem(db.Model):
    """One food item within a meal, as parsed/edited."""
    __tablename__ = "food_items"

    id = db.Column(db.Integer, primary_key=True)
    meal_id = db.Column(db.Integer, db.ForeignKey("meal_entries.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.String(50))
    calories = db.Column(db.Integer)
    protein_g = db.Column(db.Numeric(5, 1))
    carbs_g = db.Column(db.Numeric(5, 1))
    fat_g = db.Column(db.Numeric(5, 1))

    meal = db.relationship("MealEntry", back_populates="items")


class SavedMeal(db.Model):
    """
    A reusable meal template for one-tap re-logging of meals eaten repeatedly
    (e.g. a regular breakfast) — created by opting in when confirming a meal on
    the review page, not logged/parsed itself.
    """
    __tablename__ = "saved_meals"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    meal_type = db.Column(db.String(20))
    calories = db.Column(db.Integer)
    protein_g = db.Column(db.Numeric(5, 1))
    carbs_g = db.Column(db.Numeric(5, 1))
    fat_g = db.Column(db.Numeric(5, 1))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", back_populates="saved_meals")


class ExerciseEntry(db.Model):
    """A simple activity log entry: what, how long, notes."""
    __tablename__ = "exercise_entries"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    date = db.Column(db.Date, nullable=False, default=local_today)
    activity = db.Column(db.String(100), nullable=False)
    duration_min = db.Column(db.Integer)
    calories_burned = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="exercises")


class Goal(db.Model):
    """A target for a body stat or measurement, tracked against the latest entry."""
    __tablename__ = "goals"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    goal_type = db.Column(db.String(20), nullable=False)  # one of GOAL_TYPES
    target_value = db.Column(db.Numeric(6, 1), nullable=False)
    starting_value = db.Column(db.Numeric(6, 1), nullable=True)
    target_date = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    achieved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="goals")


class CoachNote(db.Model):
    """
    A durable fact about the user's health journey — goals, motivations, ongoing
    strategies, constraints — that the coach should know in every conversation,
    independent of the rolling chat-history window. Keyed so the same topic gets
    updated over time rather than duplicated (e.g. "alcohol_strategy").
    """
    __tablename__ = "coach_notes"
    __table_args__ = (db.UniqueConstraint("user_id", "key", name="uq_coach_note_user_key"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    key = db.Column(db.String(50), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", back_populates="coach_notes")


class ChatMessage(db.Model):
    """One turn of the AI coach conversation."""
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    role = db.Column(db.String(10), nullable=False)  # user | assistant
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="chat_messages")
