"""Create tables and seed the first user (from AUTH_USERNAME/AUTH_PASSWORD) if none exist."""
import os

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

from app import create_app
from app.extensions import db
from app.models import User

app = create_app()

with app.app_context():
    db.create_all()

    if User.query.count() == 0:
        username = os.environ.get("AUTH_USERNAME", "admin")
        password = os.environ.get("AUTH_PASSWORD")
        if not password:
            raise SystemExit("Set AUTH_PASSWORD in .env before running init_db.py for the first time.")
        user = User(username=username, password_hash=generate_password_hash(password), display_name=username)
        db.session.add(user)
        db.session.commit()
        print(f"Created user '{username}'. Change the password after first login.")
    else:
        print("Users already exist — skipping seed.")

print("Database ready.")
