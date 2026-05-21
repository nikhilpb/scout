from __future__ import annotations

import logging

import feedparser
import httpx
import trafilatura

from scout.agent.tools import register
from scout.agent.tools._types import ToolImpl

log = logging.getLogger("scout.tools.fetch_url")

MAX_BYTES = 200 * 1024

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "url": {"type": "string", "format": "uri"},
        "mode": {"type": "string", "enum": ["auto", "html", "rss"], "default": "auto"},
    },
    "required": ["url"],
}


def _is_feed(content_type: str, body: bytes) -> bool:
    ct = content_type.lower()
    if any(s in ct for s in ("rss", "atom", "xml")):
        return True
    head = body[:512].lower()
    return b"<rss" in head or b"<feed" in head


def _extract_html(body: bytes) -> str:
    text = trafilatura.extract(body.decode("utf-8", errors="replace")) or ""
    return text[:MAX_BYTES]


def _extract_rss(body: bytes, n: int = 10) -> str:
    parsed = feedparser.parse(body)
    parts = []
    for entry in parsed.entries[:n]:
        parts.append(
            f"{entry.get('title','(no title)')} — {entry.get('link','')}\n"
            f"{entry.get('summary','')}"
        )
    out = "\n\n".join(parts)
    return out[:MAX_BYTES]


def handler(_ctx, *, url: str, mode: str = "auto") -> dict:
    try:
        with httpx.Client(follow_redirects=True, timeout=20.0) as c:
            resp = c.get(url, headers={"User-Agent": "Scout/0.1"})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"http {e}"}
    ct = resp.headers.get("Content-Type", "")
    try:
        if mode == "rss" or (mode == "auto" and _is_feed(ct, resp.content)):
            return {"ok": True, "text": _extract_rss(resp.content)}
        return {"ok": True, "text": _extract_html(resp.content)}
    except Exception as e:
        return {"ok": False, "error": f"parse: {e}"}


register(ToolImpl(
    name="fetch_url",
    description="Fetch a URL and return cleaned text (HTML article extraction or RSS items).",
    input_schema=SCHEMA,
    runner_compat=frozenset({"builtin"}),
    default_enabled=True,
    handler=handler,
))
