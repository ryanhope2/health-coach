from app.models import ChatMessage, CoachNote, MealEntry
from tests.builders import make_chat, make_note


AJAX = {"X-Requested-With": "XMLHttpRequest"}


def test_send_stores_both_turns_and_returns_json(client, claude):
    claude.replies_text("Nice.")
    r = client.post("/coach/send", data={"message": "did a ride"}, headers=AJAX)
    assert r.get_json() == {"reply": "Nice."}
    assert [(m.role, m.content) for m in ChatMessage.query.order_by(ChatMessage.id)] == [
        ("user", "did a ride"), ("assistant", "Nice.")]


def test_send_without_js_redirects(client, claude):
    claude.replies_text("Nice.")
    assert client.post("/coach/send", data={"message": "hi"}).headers["Location"] == "/coach/"


def test_empty_message_does_not_call_the_model(client):
    r = client.post("/coach/send", data={"message": "  "}, headers=AJAX)
    assert r.status_code == 400
    assert ChatMessage.query.count() == 0


def test_history_excludes_the_new_message_and_other_users(client, user, other_user, claude):
    make_chat(user, "user", "older question")
    make_chat(user, "assistant", "older answer")
    make_chat(other_user, "user", "their message")
    claude.replies_text("ok")
    client.post("/coach/send", data={"message": "new"}, headers=AJAX)
    sent = claude.calls[0]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assert sent[0]["content"][0]["text"].endswith("older question")
    assert sent[1]["content"][0]["text"].endswith("older answer")
    assert sent[2]["content"][-1]["text"].endswith("new")
    assert "their message" not in str(sent)


def test_ai_failure_still_stores_a_reply(client, claude):
    claude.fails()
    r = client.post("/coach/send", data={"message": "hi"}, headers=AJAX)
    assert "error" in r.get_json()["reply"]
    assert ChatMessage.query.count() == 2


def test_chat_can_log_a_meal_end_to_end(client, claude):
    claude.calls_tool("log_meal", {"description": "burrito", "meal_type": "lunch",
                                   "calories": 900, "protein_g": 40})
    claude.replies_text("Logged: 900 kcal.")
    client.post("/coach/send", data={"message": "had a burrito"}, headers=AJAX)
    assert MealEntry.query.one().description == "burrito"


def test_clear(client, user):
    make_chat(user)
    client.post("/coach/clear")
    assert ChatMessage.query.count() == 0


def test_add_note_normalizes_and_upserts(client, user):
    make_note(user, key="travel", content="old")
    client.post("/coach/notes/new", data={"key": "Travel", "content": "new"})
    assert [(n.key, n.content) for n in CoachNote.query.all()] == [("travel", "new")]


def test_update_and_delete_note(client, user):
    n = make_note(user)
    client.post(f"/coach/notes/{n.id}/update", data={"key": "Trip Plans", "content": "Paris"})
    assert (n.key, n.content) == ("trip_plans", "Paris")
    client.post(f"/coach/notes/{n.id}/delete")
    assert CoachNote.query.count() == 0


def test_note_needs_key_and_content(client):
    client.post("/coach/notes/new", data={"key": "", "content": "x"})
    assert CoachNote.query.count() == 0
