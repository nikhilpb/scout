from __future__ import annotations

from scout.agent.tools import register
from scout.agent.tools._types import ToolImpl

MAX_BYTES = 200 * 1024

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "url": {"type": "string", "format": "uri"},
        "wait_for_selector": {"type": "string"},
    },
    "required": ["url"],
}


def handler(_ctx, *, url: str, wait_for_selector: str | None = None) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"ok": False, "error": "playwright not installed"}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, timeout=20_000)
                if wait_for_selector:
                    page.wait_for_selector(wait_for_selector, timeout=10_000)
                text = page.evaluate("() => document.body.innerText")
            finally:
                browser.close()
    except Exception as e:
        return {"ok": False, "error": f"browser: {e}"}
    return {"ok": True, "text": (text or "")[:MAX_BYTES]}


register(ToolImpl(
    name="browser_use",
    description="Render a URL in headless Chromium and return DOM text.",
    input_schema=SCHEMA,
    runner_compat=frozenset({"builtin"}),
    default_enabled=False,  # opt-in
    handler=handler,
))
