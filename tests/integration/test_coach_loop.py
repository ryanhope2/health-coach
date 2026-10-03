"""get_response: the tool-use loop between the model and _execute_tool."""
import json

from app.ai_coach import MAX_TOOL_ROUNDS, get_response
from app.models import MealEntry


def test_plain_reply(user, claude):
    claude.replies_text("Looking good.")
    assert get_response("key", user, [], "how am I doing?") == "Looking good."


def test_context_and_history_are_sent(user, claude, clock):
    clock.at("2026-09-30 09:00")
    claude.replies_text("ok")
    history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "reply"}]
    get_response("key", user, history, "now")
    call = claude.calls[0]
    assert "Current week (Sun-Sat): 2026-09-27" in call["system"]
    assert call["messages"] == history + [{"role": "user", "content": "now"}]
    assert {t["name"] for t in call["tools"]} >= {"log_meal", "log_exercise", "save_note"}


def test_tool_call_is_executed_and_its_result_sent_back(user, claude):
    claude.calls_tool("log_meal", {"description": "salad", "calories": 400, "protein_g": 30})
    claude.replies_text("Logged your salad.")
    assert get_response("key", user, [], "had a salad") == "Logged your salad."
    assert MealEntry.query.one().description == "salad"
    tool_result = claude.calls[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert json.loads(tool_result["content"])["success"] is True


def test_tool_errors_go_back_to_the_model_not_the_user(user, claude):
    claude.calls_tool("log_meal", {"calories": 400})  # no protein
    claude.replies_text("How much protein?")
    assert get_response("key", user, [], "ate stuff") == "How much protein?"
    assert "error" in json.loads(claude.calls[1]["messages"][-1]["content"][0]["content"])


def test_gives_up_after_max_tool_rounds(user, claude):
    for _ in range(MAX_TOOL_ROUNDS):
        claude.calls_tool("save_note", {"key": "k", "content": "c"})
    reply = get_response("key", user, [], "loop forever")
    assert "check your logs" in reply
    assert len(claude.calls) == MAX_TOOL_ROUNDS
