"""What conversation history the coach gets (load_history) and how it's presented: a
time-based window, every message stamped with when it was sent in local time."""
from datetime import timedelta

import pytest

from app.ai_coach import HISTORY_MAX, HISTORY_MIN, get_response, load_history
from tests.builders import day, local_dt, make_chat


def chat_pairs(user, d, n, start="08:00"):
    """n user/assistant pairs on local day d, a minute apart."""
    t = local_dt(d, start)
    for i in range(n):
        make_chat(user, "user", f"{d} q{i}", at=t + timedelta(minutes=2 * i))
        make_chat(user, "assistant", f"{d} a{i}", at=t + timedelta(minutes=2 * i + 1))


@pytest.fixture(autouse=True)
def frozen(clock):
    clock.at("2026-09-30 21:00")  # Wednesday = day(3)


def contents(history):
    return [m["content"] for m in history]


# --- the window ----------------------------------------------------------------------------

def test_keeps_all_of_today_and_yesterday_beyond_the_minimum(user):
    chat_pairs(user, day(1), 5)
    chat_pairs(user, day(2), 15)
    chat_pairs(user, day(3), 10)
    history = load_history(user.id)
    assert len(history) == 50  # yesterday + today, all of it
    assert history[0]["content"] == f"{day(2)} q0"


def test_reaches_back_to_the_minimum_on_a_quiet_day(user):
    chat_pairs(user, day(-5), 30)
    make_chat(user, "user", "today q", at=local_dt(day(3), "09:00"))
    make_chat(user, "assistant", "today a", at=local_dt(day(3), "09:01"))
    history = load_history(user.id)
    assert len(history) == HISTORY_MIN
    assert contents(history)[-2:] == ["today q", "today a"]


def test_caps_at_the_maximum(user):
    chat_pairs(user, day(3), HISTORY_MAX)  # 2x the cap, all today
    history = load_history(user.id)
    assert len(history) == HISTORY_MAX
    assert history[-1]["content"] == f"{day(3)} a{HISTORY_MAX - 1}"


def test_never_starts_with_an_assistant_message(user):
    make_chat(user, "assistant", "orphan", at=local_dt(day(2), "08:00"))
    chat_pairs(user, day(2), 2, start="09:00")
    assert load_history(user.id)[0]["role"] == "user"


def test_ties_keep_insertion_order(user):
    t = local_dt(day(3), "09:00")
    make_chat(user, "user", "first", at=t)
    make_chat(user, "assistant", "second", at=t)
    assert contents(load_history(user.id)) == ["first", "second"]


def test_only_the_users_own_messages(user, other_user):
    make_chat(other_user, "user", "theirs", at=local_dt(day(3), "09:00"))
    assert load_history(user.id) == []


def test_empty(user):
    assert load_history(user.id) == []


# --- what the model is sent ----------------------------------------------------------------

def test_every_message_is_stamped_with_its_local_send_time(user, claude):
    make_chat(user, "user", "had eggs", at=local_dt(day(2), "20:10"))  # after UTC midnight
    make_chat(user, "assistant", "logged", at=local_dt(day(2), "20:11"))
    claude.replies_text("ok")
    get_response("key", user, load_history(user.id), "and now?")
    sent = claude.calls[0]["messages"]
    assert sent[0]["content"][0]["text"] == "[Tue Sep 29, 8:10 PM] had eggs"
    assert sent[1]["content"][0]["text"] == "[Tue Sep 29, 8:11 PM] logged"
    assert sent[-1]["content"][-1]["text"] == "[Wed Sep 30, 9:00 PM] and now?"


def test_stored_messages_are_not_stamped(client, user, claude):
    claude.replies_text("ok")
    client.post("/coach/send", data={"message": "hi"})
    from app.models import ChatMessage
    assert [m.content for m in ChatMessage.query.order_by(ChatMessage.id)] == ["hi", "ok"]
