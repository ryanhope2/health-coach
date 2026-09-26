"""Write the weekly recap for the week that just ended, for every user with a current
period. Run Sunday morning by cron (see `./run setup`); safe to re-run — it rewrites the
existing recap for that week rather than adding another."""
from datetime import timedelta

from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.models import User
from app.progress import week_start
from app.recap import generate_recap
from app.timeutils import local_today

app = create_app()

with app.app_context():
    last_week = week_start(local_today()) - timedelta(days=7)
    for user in User.query.all():
        period = user.current_period()
        if period is None or last_week + timedelta(days=6) < period.start_date or last_week > period.end_date:
            continue
        try:
            generate_recap(app.config["ANTHROPIC_API_KEY"], user, period, last_week)
            print(f"{user.username}: wrote recap for week of {last_week}")
        except Exception as e:
            print(f"{user.username}: recap for week of {last_week} failed: {e}")
