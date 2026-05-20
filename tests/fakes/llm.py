from __future__ import annotations

from scout.agent.llm import Response


class FakeLLMClient:
    def __init__(self, scripted: list[Response]):
        self._scripted = list(scripted)
        self.calls = 0
        self.last_messages: list[dict] | None = None

    def call(self, messages, tools, model) -> Response:
        self.last_messages = list(messages)
        self.calls += 1
        if not self._scripted:
            raise AssertionError("FakeLLMClient exhausted")
        return self._scripted.pop(0)
