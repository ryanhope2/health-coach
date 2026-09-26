"""
Introduce TrackingPeriod (one-time migration, safe to re-run):
  - adds goals.period_id and meal_entries.drinks
  - creates the tracking_periods table
  - seeds one period per user from the old users.tracking_period_start / daily targets,
    ending on the latest active goal's target date, and attaches active goals to it
  - sets drinks = 1 on existing alcohol entries (fix multi-drink entries by hand after)
"""
import os
import sqlite3
from datetime import date, timedelta

from dotenv import load_dotenv
load_dotenv()

DB_PATH = os.path.join("instance", "moronfitness.db")

NEW_COLUMNS = [
    ("goals", "period_id", "INTEGER REFERENCES tracking_periods(id)"),
    ("meal_entries", "drinks", "NUMERIC(3,1)"),
]

SEASONS = {12: "Winter", 1: "Winter", 2: "Winter", 3: "Spring", 4: "Spring", 5: "Spring",
           6: "Summer", 7: "Summer", 8: "Summer", 9: "Fall", 10: "Fall", 11: "Fall"}


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH} — run init_db.py first.")
        return

    # New table via the models, so its schema can't drift from app/models.py.
    from app import create_app
    from app.extensions import db
    with create_app().app_context():
        db.create_all()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for table, col, col_type in NEW_COLUMNS:
        cur.execute(f"PRAGMA table_info({table})")
        if col not in {row[1] for row in cur.fetchall()}:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            print(f"Added {table}.{col}")

    users = cur.execute(
        "SELECT id, username, tracking_period_start, daily_calorie_target, daily_protein_target_g FROM users"
    ).fetchall()
    for user_id, username, start, calories, protein in users:
        if cur.execute("SELECT 1 FROM tracking_periods WHERE user_id = ?", (user_id,)).fetchone():
            print(f"{username}: already has a period — skipping")
            continue
        if not start:
            print(f"{username}: no tracking_period_start — skipping (create one on the Goals page)")
            continue
        start_date = date.fromisoformat(start)
        end = cur.execute(
            "SELECT MAX(target_date) FROM goals WHERE user_id = ? AND is_active = 1", (user_id,)
        ).fetchone()[0]
        end_date = date.fromisoformat(end) if end else start_date + timedelta(weeks=12)
        name = f"{SEASONS[start_date.month]} {start_date.year}"
        cur.execute(
            "INSERT INTO tracking_periods (user_id, name, start_date, end_date, daily_calorie_target, "
            "daily_protein_target_g, weekly_exercise_days_target, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 4, CURRENT_TIMESTAMP)",
            (user_id, name, start_date.isoformat(), end_date.isoformat(), calories, protein),
        )
        period_id = cur.lastrowid
        cur.execute(
            "UPDATE goals SET period_id = ? WHERE user_id = ? AND is_active = 1 AND period_id IS NULL",
            (period_id, user_id),
        )
        print(f"{username}: created \"{name}\" {start_date} to {end_date}, attached {cur.rowcount} goal(s)")

    cur.execute("UPDATE meal_entries SET drinks = 1 WHERE meal_type = 'alcohol' AND drinks IS NULL")
    print(f"Set drinks = 1 on {cur.rowcount} existing alcohol entr(ies)")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    migrate()
