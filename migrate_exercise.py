"""Add structured exercise columns to exercise_entries (one-time migration)."""
import sqlite3
import os

from dotenv import load_dotenv
load_dotenv()

DB_PATH = os.path.join("instance", "moronfitness.db")

NEW_COLUMNS = [
    ("exercise_type", "TEXT"),
    ("sets",          "INTEGER"),
    ("reps",          "INTEGER"),
    ("weight_lbs",    "NUMERIC(5,1)"),
    ("hang_seconds",  "INTEGER"),
    ("rest_seconds",  "INTEGER"),
]

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH} — run init_db.py first.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(exercise_entries)")
    existing = {row[1] for row in cur.fetchall()}

    added = []
    for col_name, col_type in NEW_COLUMNS:
        if col_name not in existing:
            cur.execute(f"ALTER TABLE exercise_entries ADD COLUMN {col_name} {col_type}")
            added.append(col_name)

    conn.commit()
    conn.close()

    if added:
        print(f"Added columns: {', '.join(added)}")
    else:
        print("All columns already present — nothing to do.")

if __name__ == "__main__":
    migrate()
