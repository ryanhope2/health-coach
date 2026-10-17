"""get_response: request shape (static system prompt, data block in the latest message,
cache breakpoints) and the tool-use loop."""
import json

from app.ai_coach import CHAT_EFFORT, CHAT_MODEL, MAX_TOOL_ROUNDS, SYSTEM_PROMPT, get_response
from app.models import MealEntry
from tests.builders import day, local_dt, log_meal, make_chat


def text_of(message):
    return "\n".join(b["text"] for b in message["content"] if b.get("type") == "text")


def test_plain_reply(user, claude):
    claude.replies_text("Looking good.")
    assert get_response("key", user, [], "how am I doing?") == "Looking good."


def test_system_prompt_is_static(user, other_user, claude, clock):
    # Nothing per-user or per-moment in the system prompt, so it (and the tools) cache.
    clock.at("2026-09-30 09:00")
    claude.replies_text("ok")
    get_response("key", user, [], "a")
    clock.at("2026-10-01 18:00")
    log_meal(other_user, day(4))
    claude.replies_text("ok")
    get_response("key", other_user, [], "b")
    first, second = (c["system"] for c in claude.calls)
    assert first == second
    assert first[0]["text"] == SYSTEM_PROMPT
    assert first[0]["cache_control"] == {"type": "ephemeral"}


def test_data_block_rides_in_the_latest_message(user, claude, clock):
    clock.at("2026-09-30 09:00")
    claude.replies_text("ok")
    get_response("key", user, [], "now")
    last = claude.calls[0]["messages"][-1]
    assert last["role"] == "user"
    assert "Current week (Sun-Sat): 2026-09-27" in text_of(last)
    assert text_of(last).rstrip().endswith("now")


def test_history_ends_with_a_cache_breakpoint(user, claude, clock):
    clock.at("2026-09-30 09:00")
    make_chat(user, "user", "q", at=local_dt(day(3), "08:00"))
    make_chat(user, "assistant", "a", at=local_dt(day(3), "08:01"))
    claude.replies_text("ok")
    from app.ai_coach import load_history
    get_response("key", user, load_history(user.id), "now")
    sent = claude.calls[0]["messages"]
    assert sent[1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in sent[0]["content"][-1]
    assert all("cache_control" not in b for b in sent[-1]["content"])


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


# --- Sonnet 5.5: thinking, effort, refusals -------------------------------------------------

def test_request_settings(user, claude):
    claude.replies_text("ok")
    get_response("key", user, [], "hi")
    call = claude.calls[0]
    assert call["model"] == CHAT_MODEL == "claude-sonnet-5-5"
    assert call["output_config"] == {"effort": CHAT_EFFORT}
    assert CHAT_EFFORT == "medium"
    assert call["max_tokens"] >= 8000  # thinking counts toward it
    assert "tool_choice" not in call


def test_thinking_blocks_are_passed_back_unchanged_within_a_turn(user, claude):
    claude.calls_tool("save_note", {"key": "k", "content": "c"})
    claude.replies_text("Saved.")
    get_response("key", user, [], "remember this")
    first_response_blocks = claude.calls[1]["messages"][-2]["content"]
    assert first_response_blocks[0].type == "thinking"
    assert [b.type for b in first_response_blocks] == ["thinking", "tool_use"]


def test_a_refusal_becomes_a_friendly_reply(user, claude):
    claude.refuses()
    reply = get_response("key", user, [], "something")
    assert reply and "couldn't help with that" in reply
