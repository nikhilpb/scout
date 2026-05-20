from __future__ import annotations

import os
from typing import Any

import httpx

from scout.agent.tools import register
from scout.agent.tools._types import ToolImpl

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_CACHE: dict[tuple[str, int], dict[str, Any]] = {}

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "query": {"type": "string", "minLength": 1},
        "num_results": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
    },
    "required": ["query"],
}


def handler(_ctx, *, query: str, num_results: int = 5) -> dict:
    key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not key:
        return {"ok": False, "error": "BRAVE_SEARCH_API_KEY missing"}
    cache_key = (query, num_results)
    if cache_key in _CACHE:
        return _CACHE[cache_key]
    try:
        with httpx.Client(timeout=20.0) as c:
            resp = c.get(
                ENDPOINT,
                headers={"X-Subscription-Token": key, "Accept": "application/json"},
                params={"q": query, "count": num_results},
            )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"http {e}"}
    data = resp.json()
    results = [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", "")}
        for r in data.get("web", {}).get("results", [])[:num_results]
    ]
    out = {"ok": True, "results": results}
    _CACHE[cache_key] = out
    return out


register(ToolImpl(
    name="web_search",
    description="Search the web (Brave). Returns a list of {title, url, snippet}.",
    input_schema=SCHEMA,
    runner_compat=frozenset({"builtin"}),
    default_enabled=True,
    handler=handler,
))
