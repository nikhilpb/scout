import litellm
import pytest

from scout.agent.llm import LLMClient


class _Resp:
    def __init__(self):
        self.choices = [
            type("C", (), {"message": type("M", (), {"content": "ok", "tool_calls": []})()})
        ]
        self.usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1})()


def test_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_completion(**kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise litellm.RateLimitError("slow down", llm_provider="x", model="m")
        return _Resp()

    monkeypatch.setattr(litellm, "completion", fake_completion)
    monkeypatch.setattr("time.sleep", lambda s: None)
    r = LLMClient().call([], [], "m")
    assert r.text == "ok"
    assert calls["n"] == 3


def test_non_transient_not_retried(monkeypatch):
    calls = {"n": 0}

    class BoomAuth(Exception):
        pass

    monkeypatch.setattr(litellm, "AuthenticationError", BoomAuth, raising=False)

    def fake_completion(**kw):
        calls["n"] += 1
        raise BoomAuth("bad key")

    monkeypatch.setattr(litellm, "completion", fake_completion)
    with pytest.raises(BoomAuth):
        LLMClient().call([], [], "m")
    assert calls["n"] == 1
