import pytest
from pydantic import ValidationError

from scout.config import TopicConfig

VALID_MIN = {
    "title": "AI research",
    "description": "Frontier AI research.",
    "cadence": "0 7 * * *",
    "model": "m",
    "prompt": {"template": "briefing"},
}


def test_valid_minimal_config():
    cfg = TopicConfig(**VALID_MIN)
    assert cfg.title == "AI research"
    assert cfg.runner == "builtin"
    assert cfg.limits is None or cfg.limits.timeout_seconds is None


def test_invalid_cadence_rejected():
    bad = dict(VALID_MIN, cadence="every monday")
    with pytest.raises(ValidationError):
        TopicConfig(**bad)


def test_prompt_exactly_one_of():
    bad = dict(VALID_MIN, prompt={"template": "briefing", "inline": "hi"})
    with pytest.raises(ValidationError):
        TopicConfig(**bad)
    bad2 = dict(VALID_MIN, prompt={})
    with pytest.raises(ValidationError):
        TopicConfig(**bad2)


def test_runner_enum():
    ok = dict(VALID_MIN, runner="claude-code")
    TopicConfig(**ok)
    with pytest.raises(ValidationError):
        TopicConfig(**dict(VALID_MIN, runner="bogus"))


def test_model_required_for_builtin():
    bad = dict(VALID_MIN)
    bad.pop("model", None)
    with pytest.raises(ValidationError):
        TopicConfig(**bad)


def test_model_optional_for_cli_runner():
    cfg_data = dict(VALID_MIN, runner="claude-code")
    cfg_data.pop("model", None)
    cfg = TopicConfig(**cfg_data)
    assert cfg.model is None


def test_tools_must_be_subset():
    bad = dict(VALID_MIN, tools=["bogus_tool"])
    with pytest.raises(ValidationError):
        TopicConfig(**bad)


def test_timeout_positive():
    bad = dict(VALID_MIN, limits={"timeout_seconds": 0})
    with pytest.raises(ValidationError):
        TopicConfig(**bad)


def test_source_types():
    ok = dict(
        VALID_MIN,
        sources=[
            {"type": "rss", "url": "https://x/feed"},
            {"type": "web", "url": "https://x/blog"},
            {"type": "search", "query": "foo"},
        ],
    )
    cfg = TopicConfig(**ok)
    assert len(cfg.sources) == 3
    assert cfg.sources[2].query == "foo"
