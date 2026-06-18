from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import litellm
import openai

log = logging.getLogger("scout.agent.llm")

# Common base for every provider-side completion failure. litellm raises a mix
# of its own exception types and re-exported openai ones, but all of them
# ultimately subclass openai.APIError (including litellm.APIError itself), so
# this single type is what callers catch to handle "the LLM call failed" —
# transient or not — without crashing.
LLMCallError = openai.APIError

# Provider-side failures worth retrying with backoff: rate limits (429),
# connection drops, timeouts, and transient 5xx server errors (500/503 — e.g.
# Gemini's "this model is currently experiencing high demand"). These usually
# clear on their own. Client errors (bad request, auth, context-window) are
# deliberately excluded — they fail identically on retry. Missing names are
# filtered out so an `except ()` simply never matches rather than over-catching.
_TRANSIENT: tuple[type[BaseException], ...] = tuple(
    cls
    for cls in (
        getattr(litellm, name, None)
        for name in (
            "RateLimitError",
            "APIConnectionError",
            "Timeout",
            "ServiceUnavailableError",
            "InternalServerError",
        )
    )
    if isinstance(cls, type) and issubclass(cls, BaseException)
)

_MAX_ATTEMPTS = 5
_BASE_DELAY = 2.0
_MAX_DELAY = 30.0


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
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = litellm.completion(
                    model=model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                )
                break
            except _TRANSIENT as e:
                if attempt == _MAX_ATTEMPTS - 1:
                    log.warning(
                        "LLM call to %s failed after %d attempts: %s",
                        model, _MAX_ATTEMPTS, e,
                    )
                    raise
                # Exponential backoff with jitter — the jitter desynchronizes
                # retries so concurrent topics don't hammer a struggling provider
                # in lockstep.
                backoff = min(_BASE_DELAY * 2**attempt, _MAX_DELAY)
                delay = backoff + random.uniform(0, backoff / 2)
                log.warning(
                    "transient LLM error from %s (attempt %d/%d), retrying in %.1fs: %s",
                    model, attempt + 1, _MAX_ATTEMPTS, delay, e,
                )
                time.sleep(delay)
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
