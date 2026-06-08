from datetime import datetime, timedelta, timezone
from pathlib import Path

from scout.config import LoadedTopic, Prompt, TopicConfig
from scout.runner import Paths, apply_time_window, format_run_time
from scout.runners.builtin import BuiltinRunner
from scout.runners.claude_code import ClaudeCodeRunner
from scout.runners.codex import CodexRunner

NOW = datetime(2026, 6, 8, 3, 0, tzinfo=timezone.utc)
LAST = datetime(2026, 6, 7, 3, 0, tzinfo=timezone.utc)


def test_format_run_time_is_utc_minute_precision():
    assert format_run_time(NOW) == "2026-06-08 03:00 UTC"


def test_format_run_time_converts_to_utc():
    # A non-UTC tz-aware datetime is normalised to UTC before formatting.
    plus2 = timezone(timedelta(hours=2))
    assert format_run_time(NOW.astimezone(plus2)) == "2026-06-08 03:00 UTC"


def test_format_run_time_treats_naive_as_utc():
    # A naive datetime (e.g. a legacy/hand-edited state file) is assumed UTC,
    # not the host's local zone — so the boundary can't silently shift.
    assert format_run_time(NOW.replace(tzinfo=None)) == "2026-06-08 03:00 UTC"


def test_apply_time_window_substitutes_both():
    out = apply_time_window(
        "from {{last_run}} to {{now}}", now=NOW, last_run=LAST
    )
    assert out == "from 2026-06-07 03:00 UTC to 2026-06-08 03:00 UTC"


def test_apply_time_window_cold_start():
    out = apply_time_window("since {{last_run}}", now=NOW, last_run=None)
    assert "no previous run" in out
    assert "{{last_run}}" not in out


def test_cadence_window_renders_real_window():
    out = apply_time_window("Period: {{cadence_window}}.", now=NOW, last_run=LAST)
    assert out == (
        "Period: since the last run at 2026-06-07 03:00 UTC, "
        "through 2026-06-08 03:00 UTC."
    )


def test_cadence_window_cold_start_is_grammatical():
    out = apply_time_window("Period: {{cadence_window}}.", now=NOW, last_run=None)
    assert out == "Period: this topic's first run (covering up to 2026-06-08 03:00 UTC)."
    assert "{{" not in out


def test_apply_time_window_leaves_unused_placeholders():
    # Unrelated placeholders are untouched; safe for prompts that don't opt in.
    assert apply_time_window("{{title}}", now=NOW, last_run=LAST) == "{{title}}"


def _topic(inline: str) -> LoadedTopic:
    return LoadedTopic(
        slug="t",
        path=Path("t.yaml"),
        config=TopicConfig(
            title="T",
            description="d",
            cadence="0 3 * * *",
            model="anthropic/claude-sonnet-4-6",
            prompt=Prompt(inline=inline),
        ),
    )


def test_builtin_injects_window_into_user_prompt():
    topic = _topic("window: {{last_run}} .. {{now}}")
    _system, user = BuiltinRunner()._build_prompts(topic, NOW, LAST)
    assert "window: 2026-06-07 03:00 UTC .. 2026-06-08 03:00 UTC" in user


def test_claude_code_injects_window_into_prompt():
    topic = _topic("window: {{last_run}} .. {{now}}")
    prompt = ClaudeCodeRunner()._build_prompt(topic, NOW, LAST)
    assert "window: 2026-06-07 03:00 UTC .. 2026-06-08 03:00 UTC" in prompt


def test_codex_injects_window_into_prompt():
    topic = _topic("window: {{last_run}} .. {{now}}")
    paths = Paths(output_dir=Path("."), logs_dir=Path("."))
    prompt = CodexRunner()._build_prompt(topic, NOW, paths, LAST)
    assert "window: 2026-06-07 03:00 UTC .. 2026-06-08 03:00 UTC" in prompt
