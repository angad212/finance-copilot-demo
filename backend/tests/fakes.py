from types import SimpleNamespace


def text_response(text):
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


def tool_response(sql, tool_id="t1"):
    block = SimpleNamespace(type="tool_use", id=tool_id, name="run_sql_query", input={"sql": sql})
    return SimpleNamespace(stop_reason="tool_use", content=[block], usage=SimpleNamespace(input_tokens=10, output_tokens=5))


class FakeLLM:
    """Stands in for the Anthropic client so tests are free, fast, and repeatable.

    Pass `replies` (a list consumed in order) or `fn` (called with the request kwargs).
    Replies may be strings, ready-made responses, or exceptions to raise.
    """

    def __init__(self, replies=None, fn=None):
        self.replies = list(replies or [])
        self.fn = fn
        self.calls = []
        self.messages = self  # so client.messages.create(...) lands on create()

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.fn(kwargs) if self.fn else self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return text_response(item) if isinstance(item, str) else item
