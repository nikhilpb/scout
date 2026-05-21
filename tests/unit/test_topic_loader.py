import logging
import textwrap

import pytest

from scout.config import ConfigError, load_all_topics, load_topic


def write(p, body):
    p.write_text(textwrap.dedent(body))


def test_load_topic_happy_path(tmp_path):
    p = tmp_path / "ai-research.yaml"
    write(p, """
        title: "AI research"
        description: "Frontier."
        cadence: "0 7 * * *"
        model: "m"
        prompt:
          template: briefing
    """)
    loaded = load_topic(p)
    assert loaded.slug == "ai-research"
    assert loaded.config.title == "AI research"


def test_invalid_filename_rejected(tmp_path):
    p = tmp_path / "AI_Research.yaml"  # uppercase + underscore
    p.write_text("title: x")
    with pytest.raises(ConfigError):
        load_topic(p)


def test_non_yaml_extension_rejected(tmp_path):
    p = tmp_path / "ai.json"
    p.write_text("{}")
    with pytest.raises(ConfigError):
        load_topic(p)


def test_load_all_skips_invalid(tmp_path, caplog):
    good = tmp_path / "good.yaml"
    write(good, """
        title: "Good"
        description: "d"
        cadence: "0 * * * *"
        model: "m"
        prompt: {template: briefing}
    """)
    bad = tmp_path / "bad.yaml"
    bad.write_text("not: { valid: cron }")  # missing required fields
    with caplog.at_level(logging.ERROR):
        topics = load_all_topics(tmp_path)
    assert "good" in topics
    assert "bad" not in topics
    assert any("bad.yaml" in r.message for r in caplog.records)


def test_warning_for_tools_on_cli_runner(tmp_path, caplog):
    p = tmp_path / "x.yaml"
    write(p, """
        title: x
        description: d
        cadence: "0 * * * *"
        runner: claude-code
        prompt: {template: briefing}
        tools: [web_search]
    """)
    with caplog.at_level(logging.WARNING):
        loaded = load_topic(p)
    assert any("tools" in r.message.lower() for r in caplog.records)
    assert loaded.config.tools == ["web_search"]  # value preserved
