from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import litellm  # noqa: F401

_TRANSIENT = (
    getattr(litellm, "RateLimitError", Exception),
    getattr(litellm, "APIConnectionError", Exception),
    getattr(litellm, "Timeout", Exception),
)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class Response:
    text: Optional[str]
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    raw: Any = None


class LLMClient:
    def call(self, messages: list[dict], tools: list[dict], model: str) -> Response:
        import json
        import time as _time
        delay = 2.0
        for attempt in range(3):
            try:
                resp = litellm.completion(
                    model=model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                )
                break
            except _TRANSIENT:
                if attempt == 2:
                    raise
                _time.sleep(min(delay, 8.0))
                delay *= 2
        msg = resp.choices[0].message
        calls = []
        for tc in (msg.tool_calls or []):
            calls.append(ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=json.loads(tc.function.arguments or "{}"),
            ))
        usage = getattr(resp, "usage", None) or type(
            "U", (), {"prompt_tokens": 0, "completion_tokens": 0}
        )()
        try:
            cost = float(litellm.completion_cost(completion_response=resp) or 0.0)
        except Exception:
            cost = 0.0
        return Response(
            text=msg.content,
            tool_calls=calls,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            cost_usd=cost,
            raw=resp,
        )
