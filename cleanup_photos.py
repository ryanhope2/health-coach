"""
Delete meal photos older than PHOTO_RETENTION_DAYS (default 30). Run daily via cron.
The MealEntry row and its nutrition data are kept — only the image file is removed
and photo_path is cleared.
"""
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import db
from app.models import MealEntry

app = create_app()

with app.app_context():
    cutoff = datetime.utcnow() - timedelta(days=app.config["PHOTO_RETENTION_DAYS"])
    old_meals = MealEntry.query.filter(
        MealEntry.photo_path.isnot(None),
        MealEntry.created_at < cutoff,
    ).all()

    deleted = 0
    for meal in old_meals:
        path = Path(meal.photo_path)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue
        meal.photo_path = None
        deleted += 1

    db.session.commit()
    print(f"Deleted {deleted} photo(s) older than {app.config['PHOTO_RETENTION_DAYS']} days.")
