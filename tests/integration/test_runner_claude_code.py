import json
import os
import stat
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scout.config import LoadedTopic, TopicConfig
from scout.runlog import RunLog
from scout.runner import Limits, Paths, make_runner


def _install_fake_claude(bindir: Path, body_to_write: str, file_rel: str):
    bindir.mkdir(parents=True, exist_ok=True)
    script = bindir / "claude"
    script.write_text(textwrap.dedent(f"""\
        #!/bin/sh
        # ignore prompt argv; just produce the file
        mkdir -p "$(dirname {file_rel})"
        printf %s {body_to_write!r} > {file_rel}
    """))
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _install_streaming_fake_claude(
    bindir: Path, body_to_write: str, file_rel: str, stream_lines: list[str]
):
    """A fake `claude` that emits a stream-json transcript and writes the digest."""
    bindir.mkdir(parents=True, exist_ok=True)
    script = bindir / "claude"
    # Built line-by-line (no textwrap.dedent) so the shebang stays at column 0
    # even though the emitted JSON lines are unindented.
    lines = [
        "#!/bin/sh",
        f'mkdir -p "$(dirname {file_rel})"',
        f"printf %s {body_to_write!r} > {file_rel}",
    ]
    lines += [f"printf '%s\\n' {line!r}" for line in stream_lines]
    script.write_text("\n".join(lines) + "\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.mark.integration
def test_claude_code_runner_invokes_cli(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    out_dir = tmp_path / "output"
    logs_dir = tmp_path / "logs"
    now = datetime(2026, 5, 20, 7, tzinfo=timezone.utc)
    _install_fake_claude(bindir, body_to_write="# from-claude", file_rel="ai/2026-05-20.md")

    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    topic = LoadedTopic(
        slug="ai", path=Path("topics/ai.yaml"),
        config=TopicConfig(
            title="AI", description="AI research.",
            cadence="0 7 * * *", runner="claude-code",
            prompt={"template": "briefing"},
        ),
    )
    runner = make_runner("claude-code")
    with RunLog("ai", logs_dir, now=now) as rl:
        result = runner.execute(
            topic,
            Paths(output_dir=out_dir, logs_dir=logs_dir),
            Limits(timeout_seconds=10),
            run_log=rl, now=now,
        )
    assert result.status == "ok"
    p = out_dir / "ai" / "2026-05-20.md"
    assert p.exists()
    content = p.read_text()
    # No stream-json => metrics fall back to `unknown`, but the run still succeeds.
    assert "model: unknown" in content
    assert "# from-claude" in content


@pytest.mark.integration
def test_claude_code_runner_captures_metrics(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    out_dir = tmp_path / "output"
    logs_dir = tmp_path / "logs"
    now = datetime(2026, 5, 20, 7, tzinfo=timezone.utc)
    stream_lines = [
        json.dumps({"type": "system", "subtype": "init", "model": "claude-sonnet-4-6"}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "WebSearch", "input": {}}]}}),
        # duplicate id — must not be double-counted
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "WebSearch", "input": {}}]}}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t2", "name": "WebFetch", "input": {}}]}}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t3", "name": "Write", "input": {}}]}}),
        json.dumps({
            "type": "result", "subtype": "success", "is_error": False,
            "num_turns": 4, "total_cost_usd": 0.0123,
            "modelUsage": {"claude-sonnet-4-6": {
                "inputTokens": 1000, "outputTokens": 200,
                "cacheReadInputTokens": 5000, "cacheCreationInputTokens": 300,
                "costUSD": 0.0123}},
            "permission_denials": [],
        }),
    ]
    _install_streaming_fake_claude(
        bindir, body_to_write="# digest body", file_rel="ai/2026-05-20.md",
        stream_lines=stream_lines,
    )
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    topic = LoadedTopic(
        slug="ai", path=Path("topics/ai.yaml"),
        config=TopicConfig(
            title="AI", description="AI research.",
            cadence="0 7 * * *", runner="claude-code", model="claude-sonnet-4-6",
            prompt={"template": "briefing"},
        ),
    )
    runner = make_runner("claude-code")
    with RunLog("ai", logs_dir, now=now) as rl:
        result = runner.execute(
            topic,
            Paths(output_dir=out_dir, logs_dir=logs_dir),
            Limits(timeout_seconds=10),
            run_log=rl, now=now,
        )
    assert result.status == "ok"
    content = (out_dir / "ai" / "2026-05-20.md").read_text()
    assert "model: claude-sonnet-4-6" in content
    assert "cost_usd: 0.0123" in content
    # tool calls counted from the stream, duplicate id collapsed to one WebSearch
    assert result.summary["tool_calls"] == {"WebSearch": 1, "WebFetch": 1, "Write": 1}
    assert result.summary["tokens"] == {"input": 6300, "output": 200}
    assert "# digest body" in content


@pytest.mark.integration
def test_claude_code_runner_timeout_salvages_partial(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    out_dir = tmp_path / "output"
    logs_dir = tmp_path / "logs"
    now = datetime(2026, 5, 20, 7, tzinfo=timezone.utc)
    # Fake CLI (Python so it can flush like the real streaming CLI): emit two
    # tool_use events AND a full result event, flush them to the pipe, then hang
    # past the runner's timeout (models a CLI that finished the work but didn't
    # exit before we killed it).
    bindir.mkdir(parents=True)
    script = bindir / "claude"
    partial = "".join(
        json.dumps(line) + "\n" for line in [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "x1", "name": "WebSearch", "input": {}}]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "x2", "name": "WebFetch", "input": {}}]}},
            {"type": "result", "subtype": "success", "is_error": False,
             "num_turns": 2, "total_cost_usd": 0.42,
             "modelUsage": {"claude-sonnet-4-6": {
                 "inputTokens": 10, "outputTokens": 5, "costUSD": 0.42}}},
        ]
    )
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, time\n"
        f"sys.stdout.write({partial!r})\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    topic = LoadedTopic(
        slug="ai", path=Path("topics/ai.yaml"),
        config=TopicConfig(
            title="AI", description="AI research.",
            cadence="0 7 * * *", runner="claude-code", model="claude-sonnet-4-6",
            prompt={"template": "briefing"},
        ),
    )
    runner = make_runner("claude-code")
    with RunLog("ai", logs_dir, now=now) as rl:
        result = runner.execute(
            topic,
            Paths(output_dir=out_dir, logs_dir=logs_dir),
            Limits(timeout_seconds=1),
            run_log=rl, now=now,
        )
    assert result.status == "failed"
    assert result.reason == "timeout"
    # partial tool activity streamed before the kill is still recorded
    log_text = rl.path.read_text()
    assert '"timed_out": true' in log_text
    assert '"tool": "WebSearch"' in log_text
    assert '"tool": "WebFetch"' in log_text
    # cost/tokens from the salvaged result event are recorded too, not dropped
    assert result.summary["cost_usd"] == 0.42
    assert '"cost_usd": 0.42' in log_text


@pytest.mark.integration
def test_claude_code_runner_keeps_digest_on_benign_nonzero_exit(tmp_path, monkeypatch):
    # CLI writes the digest and reports success in the result event, but the
    # process exits non-zero (e.g. a benign post-run warning). The digest must
    # be kept, not discarded.
    bindir = tmp_path / "bin"
    out_dir = tmp_path / "output"
    logs_dir = tmp_path / "logs"
    now = datetime(2026, 5, 20, 7, tzinfo=timezone.utc)
    stream_lines = [
        json.dumps({"type": "system", "subtype": "init", "model": "claude-sonnet-4-6"}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "w", "name": "Write", "input": {}}]}}),
        json.dumps({"type": "result", "subtype": "success", "is_error": False,
                    "num_turns": 1, "total_cost_usd": 0.05,
                    "modelUsage": {"claude-sonnet-4-6": {
                        "inputTokens": 10, "outputTokens": 5, "costUSD": 0.05}}}),
    ]
    bindir.mkdir(parents=True)
    script = bindir / "claude"
    lines = [
        "#!/bin/sh",
        'mkdir -p "$(dirname ai/2026-05-20.md)"',
        "printf %s '# body' > ai/2026-05-20.md",
    ]
    lines += [f"printf '%s\\n' {line!r}" for line in stream_lines]
    lines += ["exit 3"]  # non-zero exit after a successful, digest-writing run
    script.write_text("\n".join(lines) + "\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    topic = LoadedTopic(
        slug="ai", path=Path("topics/ai.yaml"),
        config=TopicConfig(
            title="AI", description="AI research.",
            cadence="0 7 * * *", runner="claude-code", model="claude-sonnet-4-6",
            prompt={"template": "briefing"},
        ),
    )
    runner = make_runner("claude-code")
    with RunLog("ai", logs_dir, now=now) as rl:
        result = runner.execute(
            topic,
            Paths(output_dir=out_dir, logs_dir=logs_dir),
            Limits(timeout_seconds=10),
            run_log=rl, now=now,
        )
    assert result.status == "ok"
    content = (out_dir / "ai" / "2026-05-20.md").read_text()
    assert "# body" in content
    assert "cost_usd: 0.05" in content
