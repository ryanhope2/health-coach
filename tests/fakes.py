"""
FakeClaude: a scripted stand-in for anthropic.Anthropic.

Queue what the model will "say", in order, then exercise the code:

    claude.replies_text("Nice work.")
    claude.calls_tool("log_meal", {"calories": 400, "protein_g": 30})
    claude.saves_recap("Headline.", "Full recap.")

Each queued response is consumed by one messages.create() call. Every call's kwargs are
recorded in claude.calls (system, messages, tools, ...) so tests can assert on what was
sent. A call with nothing queued raises — an AI call nobody planned for is a test failure,
not a silent pass.
"""
import itertools
from types import SimpleNamespace

_ids = itertools.count(1)


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_use_block(name, tool_input):
    return SimpleNamespace(type="tool_use", id=f"toolu_{next(_ids)}", name=name, input=tool_input)


class FakeClaude:
    def __init__(self):
        self.queue = []
        self.calls = []

    # --- scripting ---------------------------------------------------------------------
    def responds(self, *blocks, stop_reason="end_turn"):
        self.queue.append(SimpleNamespace(content=list(blocks), stop_reason=stop_reason))
        return self

    def replies_text(self, text):
        return self.responds(text_block(text))

    def calls_tool(self, name, tool_input, text=None):
        blocks = ([text_block(text)] if text else []) + [tool_use_block(name, tool_input)]
        return self.responds(*blocks, stop_reason="tool_use")

    def saves_recap(self, headline, recap):
        return self.calls_tool("save_recap", {"headline": headline, "recap": recap})

    def fails(self, exc=RuntimeError("API down")):
        self.queue.append(exc)
        return self

    # --- the client surface the app uses -----------------------------------------------
    def client_factory(self, *args, **kwargs):
        return SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        # Snapshot messages: the app appends to the same list across tool rounds.
        self.calls.append({**kwargs, "messages": list(kwargs.get("messages", []))})
        if not self.queue:
            raise AssertionError("FakeClaude: unexpected API call — nothing queued.")
        nxt = self.queue.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    # --- helpers for assertions ----------------------------------------------------------
    @property
    def last_system(self):
        return self.calls[-1].get("system", "")

    def prompt_text(self, call_index=-1):
        """All text sent in a call's user messages, flattened (for prompts built as one
        user message, like the meal parser and the recap)."""
        out = []
        for m in self.calls[call_index]["messages"]:
            content = m["content"]
            if isinstance(content, str):
                out.append(content)
            else:
                out += [c.get("text", "") for c in content if isinstance(c, dict)]
        return "\n".join(out)
