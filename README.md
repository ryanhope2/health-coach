# Moron Fitness

Personal health & fitness tracker — weight, body fat %, measurements, meals (photo or
text, parsed by Claude), exercise, goals, and an AI coach chat that has read access to
all of it.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env: SECRET_KEY, ANTHROPIC_API_KEY, AUTH_USERNAME/AUTH_PASSWORD

python init_db.py     # creates tables + seeds the first user
python wsgi.py         # dev server on :5000
```

Add a friend later with `python manage.py add-user <username> <password>` — no UI for
this yet since it's rare.

## Production (same box as vibe-split)

```bash
gunicorn --workers 2 --worker-class gevent --bind 127.0.0.1:5003 wsgi:application
```

See `./run help` for the full deploy workflow (mirrors vibe-split's `run` script) —
`./run setup` provisions the venv, systemd service, nginx config, and a daily cron job
for photo cleanup; `./run cert` gets the SSL cert; `./run deploy` ships changes.

## Project layout

```
app/
  __init__.py          # App factory, login, dashboard route
  extensions.py        # db singleton
  models.py            # SQLAlchemy models
  meal_ai.py           # Claude Vision/text meal nutrition estimation
  ai_coach.py           # AI coach: builds context from logged data, calls Claude
  blueprints/
    body.py            # /body     — weight, body fat, measurements
    meals.py           # /meals    — log/review meals, AI parsing
    exercise.py         # /exercise — simple activity log
    goals.py            # /goals    — targets + daily nutrition targets
    coach.py            # /coach    — AI coach chat
  templates/           # Jinja2 + Bootstrap 5
instance/
  moronfitness.db       # SQLite (gitignored)
  photos/meals/         # Uploaded meal photos (gitignored), deleted after 30 days
init_db.py              # Create tables, seed first user
manage.py               # CLI: add-user, set-password, list-users
cleanup_photos.py       # Deletes meal photos older than PHOTO_RETENTION_DAYS (cron)
wsgi.py                 # Gunicorn entry point
```

See [CLAUDE.md](CLAUDE.md) for architecture notes and the full data model.
