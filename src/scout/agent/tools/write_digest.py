from __future__ import annotations

from scout.agent.tools import register
from scout.agent.tools._types import RunContext, ToolImpl
from scout.output import pick_output_path

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "markdown_body": {"type": "string", "minLength": 1},
    },
    "required": ["markdown_body"],
}


def handler(ctx: RunContext, *, markdown_body: str) -> dict:
    path = pick_output_path(ctx.slug, ctx.output_dir, ctx.now)
    path.write_text(markdown_body)
    return {"ok": True, "path": str(path)}


register(ToolImpl(
    name="write_digest",
    description="Write the final markdown digest body for this run.",
    input_schema=SCHEMA,
    runner_compat=frozenset({"builtin"}),
    default_enabled=True,
    handler=handler,
))
