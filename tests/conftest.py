"""
Shared fixtures. See .claude/skills/tdd/SKILL.md for how the suite is laid out and the
red -> green workflow.

Every test gets a fresh app with its own temp SQLite DB and instance dir, so nothing
touches instance/ or the real database, and no test can reach the real Anthropic API.
"""
from datetime import datetime

import anthropic
import pytest
import time_machine
from bs4 import BeautifulSoup
from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db as _db
from app.models import User
from app.timeutils import USER_TIMEZONE

from tests.fakes import FakeClaude


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(tmp_path / "test.db"),
            "TESTING": True,
            "SECRET_KEY": "test",
            "ANTHROPIC_API_KEY": "test-key",
        },
        instance_path=str(tmp_path / "instance"),
    )
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()


@pytest.fixture
def db(app):
    return _db


def _make_user(username):
    user = User(username=username, password_hash=generate_password_hash("pw", method="pbkdf2:sha256:1"))  # fast hash for tests
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture
def user(app):
    return _make_user("me")


@pytest.fixture
def other_user(app):
    """A second account — for checking one user can never see or touch another's data."""
    return _make_user("friend")


@pytest.fixture
def anon_client(app):
    return app.test_client()


@pytest.fixture
def client(app, user, clock):
    """Test client logged in as `user`. The session cookie is signed with the current
    time, and Flask rejects one signed "in the future" — so it's re-issued whenever the
    clock moves."""
    c = app.test_client()

    def login():
        with c.session_transaction() as s:
            s["user_id"] = user.id
    login()
    clock.on_move.append(login)
    return c


class Clock:
    """Freeze the whole clock — datetime.now(tz), utcnow(), date.today() — at a moment
    given in the user's local (Eastern) time. Call at() again to move it."""

    def __init__(self):
        self._traveller = None
        self.on_move = []

    def at(self, when):
        """`when` is "YYYY-MM-DD" (noon) or "YYYY-MM-DD HH:MM", in US Eastern."""
        fmt = "%Y-%m-%d %H:%M" if " " in when else "%Y-%m-%d"
        dt = datetime.strptime(when, fmt)
        if " " not in when:
            dt = dt.replace(hour=12)
        self.stop()
        self._traveller = time_machine.travel(dt.replace(tzinfo=USER_TIMEZONE), tick=False)
        self._traveller.start()
        for callback in self.on_move:
            callback()
        return self

    def stop(self):
        if self._traveller:
            self._traveller.stop()
            self._traveller = None


@pytest.fixture
def clock():
    c = Clock()
    yield c
    c.stop()


@pytest.fixture
def claude(monkeypatch):
    """Scripted stand-in for the Anthropic client — see tests/fakes.py."""
    fake = FakeClaude()
    monkeypatch.setattr(anthropic, "Anthropic", fake.client_factory)
    return fake


@pytest.fixture(autouse=True)
def _no_real_anthropic(monkeypatch, request):
    """Any test that reaches the Anthropic API without the `claude` fixture fails loudly
    instead of making a real (billed) call."""
    if "claude" in request.fixturenames:
        return

    def refuse(*args, **kwargs):
        raise AssertionError("Test tried to call the real Anthropic API — use the `claude` fixture.")
    monkeypatch.setattr(anthropic, "Anthropic", refuse)


def soup(response):
    """Parse a test-client response as HTML, for finding elements by id/class rather than
    slicing strings."""
    return BeautifulSoup(response.get_data(as_text=True), "html.parser")
