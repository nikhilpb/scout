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


def test_retries_service_unavailable(monkeypatch):
    # Regression: a Gemini 503 ("high demand") is transient and must be retried
    # rather than crashing the runner.
    calls = {"n": 0}

    def fake_completion(**kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise litellm.ServiceUnavailableError(
                "high demand", llm_provider="gemini", model="gemini/gemini-3.5-flash"
            )
        return _Resp()

    monkeypatch.setattr(litellm, "completion", fake_completion)
    monkeypatch.setattr("time.sleep", lambda s: None)
    r = LLMClient().call([], [], "gemini/gemini-3.5-flash")
    assert r.text == "ok"
    assert calls["n"] == 3


def test_retries_internal_server_error(monkeypatch):
    calls = {"n": 0}

    def fake_completion(**kw):
        calls["n"] += 1
        if calls["n"] < 2:
            raise litellm.InternalServerError(
                "boom", llm_provider="gemini", model="m"
            )
        return _Resp()

    monkeypatch.setattr(litellm, "completion", fake_completion)
    monkeypatch.setattr("time.sleep", lambda s: None)
    r = LLMClient().call([], [], "m")
    assert r.text == "ok"
    assert calls["n"] == 2


def test_gives_up_after_max_attempts(monkeypatch):
    from scout.agent import llm as llm_mod

    calls = {"n": 0}

    def fake_completion(**kw):
        calls["n"] += 1
        raise litellm.ServiceUnavailableError(
            "down", llm_provider="gemini", model="m"
        )

    monkeypatch.setattr(litellm, "completion", fake_completion)
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(litellm.ServiceUnavailableError):
        LLMClient().call([], [], "m")
    assert calls["n"] == llm_mod._MAX_ATTEMPTS


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
