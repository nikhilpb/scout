import os

import pytest


@pytest.fixture(autouse=True)
def _route_google_key_to_gemini(monkeypatch):
    """LiteLLM's gemini provider reads GEMINI_API_KEY; alias from GOOGLE_API_KEY."""
    key = os.environ.get("GOOGLE_API_KEY")
    if key and not os.environ.get("GEMINI_API_KEY"):
        monkeypatch.setenv("GEMINI_API_KEY", key)


requires_google_key = pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="real-LLM smoke requires GOOGLE_API_KEY",
)
