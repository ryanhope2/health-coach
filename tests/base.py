import tempfile
import unittest

from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import User


class AppTestCase(unittest.TestCase):
    """Fresh app + temp SQLite DB + a logged-in test client per test."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db")
        self.app = create_app({
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + self.tmp.name,
            "TESTING": True,
        })
        with self.app.app_context():
            db.create_all()
            user = User(username="t", password_hash=generate_password_hash("x"))
            db.session.add(user)
            db.session.commit()
            self.user_id = user.id
        self.client = self.app.test_client()
        with self.client.session_transaction() as s:
            s["user_id"] = self.user_id

    def tearDown(self):
        self.tmp.close()
