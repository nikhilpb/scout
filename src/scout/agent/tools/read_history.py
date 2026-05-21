from __future__ import annotations

from scout.agent.tools import register
from scout.agent.tools._types import RunContext, ToolImpl

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"n": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}},
    "required": [],
}


def handler(ctx: RunContext, *, n: int = 5) -> dict:
    d = ctx.output_dir / ctx.slug
    if not d.exists():
        return {"ok": True, "history": ""}
    files = sorted(d.glob("*.md"), reverse=True)[:n]
    parts = []
    for f in files:
        parts.append(f"## {f.name}\n\n{f.read_text()}")
    return {"ok": True, "history": "\n\n".join(parts)}


register(ToolImpl(
    name="read_history",
    description="Read recent prior digests for this topic to avoid repetition.",
    input_schema=SCHEMA,
    runner_compat=frozenset({"builtin"}),
    default_enabled=True,
    handler=handler,
))
