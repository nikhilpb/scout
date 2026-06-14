from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal, Optional

from scout.agent.llm import LLMClient
from scout.agent.tools import registry
from scout.agent.tools._types import RunContext

log = logging.getLogger("scout.agent.loop")


@dataclass(frozen=True)
class LoopResult:
    status: Literal["ok", "failed"]
    reason: Optional[str] = None
    output_path: Optional[str] = None
    turns: int = 0


def _tools_payload(allowed: list[str]) -> list[dict]:
    reg = registry()
    out = []
    for name in allowed:
        if name not in reg:
            raise ValueError(f"allowed_tools references unregistered tool: {name!r}")
        tool = reg[name]
        out.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        })
    return out


def _dispatch(name: str, args: dict[str, Any], ctx: RunContext) -> dict:
    reg = registry()
    tool = reg.get(name)
    if tool is None:
        return {"ok": False, "error": f"unknown tool: {name}"}
    try:
        return tool.handler(ctx, **args)
    except TypeError as e:
        return {"ok": False, "error": f"bad args: {e}"}
    except Exception as e:
        log.exception("tool %s raised", name)
        return {"ok": False, "error": f"tool raised: {e}"}


def run_loop(
    *,
    client: LLMClient,
    model: str,
    system_prompt: str,
    user_prompt: str,
    ctx: RunContext,
    allowed_tools: list[str],
    timeout_seconds: float,
) -> LoopResult:
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    tools_payload = _tools_payload(allowed_tools)
    start = time.monotonic()
    turn = 0
    written_path: str | None = None

    traj = getattr(ctx, "traj", None)
    if traj is not None:
        traj.message("system", system_prompt)
        traj.message("user", user_prompt)
    while True:
        if time.monotonic() - start > timeout_seconds:
            return LoopResult(status="failed", reason="timeout", turns=turn)
        turn += 1
        resp = client.call(messages, tools_payload, model)

        assistant: dict[str, Any] = {"role": "assistant", "content": resp.text}
        if resp.tool_calls:
            assistant["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in resp.tool_calls
            ]
        messages.append(assistant)

        assistant_id: str | None = None
        if traj is not None:
            traj.note_usage(
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                cost_usd=resp.cost_usd,
            )
            content_parts: list[dict] = []
            if resp.text:
                content_parts.append({"type": "text", "text": resp.text})
            for tc in resp.tool_calls:
                content_parts.append(
                    {"type": "tool_use", "call_id": tc.id, "name": tc.name,
                     "input": tc.arguments}
                )
            assistant_id = traj.message(
                "assistant",
                content_parts,
                model=model,
                stop_reason="tool_use" if resp.tool_calls else "end_turn",
                usage={
                    "input_tokens": resp.input_tokens,
                    "output_tokens": resp.output_tokens,
                    "cost_usd": resp.cost_usd,
                },
            )

        if not resp.tool_calls:
            if written_path is None:
                return LoopResult(status="failed", reason="no_digest", turns=turn)
            return LoopResult(status="ok", output_path=written_path, turns=turn)

        for tc in resp.tool_calls:
            tool_t0 = time.monotonic()
            result = _dispatch(tc.name, tc.arguments, ctx)
            ok = bool(result.get("ok", True))
            duration_ms = int((time.monotonic() - tool_t0) * 1000)
            if traj is not None:
                call_rec = traj.tool_call(
                    call_id=tc.id, name=tc.name, arguments=tc.arguments,
                    parent_id=assistant_id,
                )
                traj.tool_result(
                    call_id=tc.id,
                    status="ok" if ok else "error",
                    result={"content": result, "bytes": len(json.dumps(result))},
                    parent_id=call_rec,
                    error=None if ok else {"message": str(result.get("error"))},
                    duration_ms=duration_ms,
                )
            messages.append({
                "role": "tool", "tool_call_id": tc.id,
                "content": json.dumps(result),
            })
            if tc.name == "write_digest" and result.get("ok"):
                written_path = result["path"]

        if written_path is not None:
            return LoopResult(status="ok", output_path=written_path, turns=turn)
