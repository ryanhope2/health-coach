"""
Small CLI for account admin — no UI for this yet since it's rare (adding a
friend, resetting a password).

Usage:
  python manage.py add-user <username> <password> [display_name]
  python manage.py set-password <username> <new_password>
  python manage.py list-users
"""
import sys

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

from app import create_app
from app.extensions import db
from app.models import User

app = create_app()


def add_user(username, password, display_name=None):
    if User.query.filter_by(username=username).first():
        print(f"User '{username}' already exists.")
        return
    user = User(username=username, password_hash=generate_password_hash(password), display_name=display_name or username)
    db.session.add(user)
    db.session.commit()
    print(f"Created user '{username}'.")


def set_password(username, password):
    user = User.query.filter_by(username=username).first()
    if not user:
        print(f"No such user: {username}")
        return
    user.password_hash = generate_password_hash(password)
    db.session.commit()
    print(f"Password updated for '{username}'.")


def list_users():
    for u in User.query.all():
        print(f"  {u.id}: {u.username} ({u.display_name})")


if __name__ == "__main__":
    with app.app_context():
        args = sys.argv[1:]
        if not args:
            print(__doc__)
        elif args[0] == "add-user" and len(args) >= 3:
            add_user(args[1], args[2], args[3] if len(args) > 3 else None)
        elif args[0] == "set-password" and len(args) >= 3:
            set_password(args[1], args[2])
        elif args[0] == "list-users":
            list_users()
        else:
            print(__doc__)
