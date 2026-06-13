import json
import os
import stat
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scout.config import LoadedTopic, TopicConfig
from scout.runner import Limits, Paths, make_runner
from scout.trajectory import TrajectoryWriter
from tests.conftest import read_trajectory


def _paths(tmp_path):
    return Paths(
        output_dir=tmp_path / "output",
        trajectories_dir=tmp_path / "trajectories",
    )


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
    with TrajectoryWriter("ai", tmp_path / "trajectories", now=now) as tw:
        result = runner.execute(
            topic, _paths(tmp_path), Limits(timeout_seconds=10), traj=tw, now=now,
        )
    assert result.status == "ok"
    p = tmp_path / "output" / "ai" / "2026-05-20.md"
    assert p.exists()
    content = p.read_text()
    # No stream-json => metrics fall back to `unknown`, but the run still succeeds.
    assert "model: unknown" in content
    assert "# from-claude" in content
    recs = read_trajectory(tw.path)
    assert recs[-1]["type"] == "result" and recs[-1]["status"] == "ok"


@pytest.mark.integration
def test_claude_code_runner_captures_metrics(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
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
    with TrajectoryWriter("ai", tmp_path / "trajectories", now=now) as tw:
        result = runner.execute(
            topic, _paths(tmp_path), Limits(timeout_seconds=10), traj=tw, now=now,
        )
    assert result.status == "ok"
    content = (tmp_path / "output" / "ai" / "2026-05-20.md").read_text()
    assert "model: claude-sonnet-4-6" in content
    assert "cost_usd: 0.0123" in content
    # tool calls counted from the stream, duplicate id collapsed to one WebSearch
    assert result.summary["tool_calls"] == {"WebSearch": 1, "WebFetch": 1, "Write": 1}
    assert result.summary["tokens"] == {"input": 6300, "output": 200}
    assert "# digest body" in content
    # the trajectory mirrors those metrics, with a per-model + cache token split
    recs = read_trajectory(tw.path)
    tool_names = [r["name"] for r in recs if r["type"] == "tool_call"]
    assert tool_names == ["WebSearch", "WebFetch", "Write"]
    res = recs[-1]
    assert res["type"] == "result" and res["status"] == "ok"
    assert res["tool_calls"] == {"WebSearch": 1, "WebFetch": 1, "Write": 1}
    assert res["usage"]["input_tokens"] == 6300
    assert res["usage"]["cache_read_input_tokens"] == 5000
    assert res["usage"]["by_model"]["claude-sonnet-4-6"]["output_tokens"] == 200
    assert res["num_turns"] == 4


@pytest.mark.integration
def test_claude_code_runner_passes_model_and_effort(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    now = datetime(2026, 5, 20, 7, tzinfo=timezone.utc)
    # Fake CLI records its argv so the test can assert on the flags it received.
    bindir.mkdir(parents=True)
    argv_file = tmp_path / "argv.txt"
    script = bindir / "claude"
    script.write_text(textwrap.dedent(f"""\
        #!/bin/sh
        printf '%s\\n' "$@" > {argv_file}
        mkdir -p ai
        printf %s '# body' > ai/2026-05-20.md
    """))
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    topic = LoadedTopic(
        slug="ai", path=Path("topics/ai.yaml"),
        config=TopicConfig(
            title="AI", description="AI research.",
            cadence="0 7 * * *", runner="claude-code", model="claude-opus-4-8",
            effort="xhigh", prompt={"template": "briefing"},
        ),
    )
    runner = make_runner("claude-code")
    with TrajectoryWriter("ai", tmp_path / "trajectories", now=now) as tw:
        result = runner.execute(
            topic, _paths(tmp_path), Limits(timeout_seconds=10), traj=tw, now=now,
        )
    assert result.status == "ok"
    argv = argv_file.read_text().splitlines()
    assert argv[argv.index("--model") + 1] == "claude-opus-4-8"
    assert argv[argv.index("--effort") + 1] == "xhigh"


@pytest.mark.integration
def test_claude_code_runner_timeout_salvages_partial(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
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
    with TrajectoryWriter("ai", tmp_path / "trajectories", now=now) as tw:
        result = runner.execute(
            topic, _paths(tmp_path), Limits(timeout_seconds=1), traj=tw, now=now,
        )
    assert result.status == "failed"
    assert result.reason == "timeout"
    # partial tool activity streamed before the kill is still recorded
    recs = read_trajectory(tw.path)
    tool_names = [r["name"] for r in recs if r["type"] == "tool_call"]
    assert "WebSearch" in tool_names and "WebFetch" in tool_names
    res = recs[-1]
    assert res["type"] == "result" and res["status"] == "failed"
    assert res["reason"] == "timeout"
    # cost/tokens from the salvaged result event are recorded too, not dropped
    assert result.summary["cost_usd"] == 0.42
    assert res["usage"]["cost_usd"] == 0.42


@pytest.mark.integration
def test_claude_code_runner_records_stderr_on_failure(tmp_path, monkeypatch):
    # CLI fails (no result event, nonzero exit) and writes a diagnostic to stderr.
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True)
    now = datetime(2026, 5, 20, 7, tzinfo=timezone.utc)
    script = bindir / "claude"
    script.write_text("#!/bin/sh\nprintf 'boom on stderr\\n' 1>&2\nexit 1\n")
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
    with TrajectoryWriter("ai", tmp_path / "trajectories", now=now) as tw:
        result = runner.execute(
            topic, _paths(tmp_path), Limits(timeout_seconds=10), traj=tw, now=now,
        )
    assert result.status == "failed"
    assert result.reason == "exit_1"
    # the failure carries the CLI's stderr so it is debuggable from the trajectory
    res = read_trajectory(tw.path)[-1]
    assert res["type"] == "result" and res["status"] == "failed"
    assert "boom on stderr" in res["error"]["stderr"]
    assert res["error"]["returncode"] == 1


@pytest.mark.integration
def test_claude_code_runner_keeps_digest_on_benign_nonzero_exit(tmp_path, monkeypatch):
    # CLI writes the digest and reports success in the result event, but the
    # process exits non-zero (e.g. a benign post-run warning). The digest must
    # be kept, not discarded.
    bindir = tmp_path / "bin"
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
    with TrajectoryWriter("ai", tmp_path / "trajectories", now=now) as tw:
        result = runner.execute(
            topic, _paths(tmp_path), Limits(timeout_seconds=10), traj=tw, now=now,
        )
    assert result.status == "ok"
    content = (tmp_path / "output" / "ai" / "2026-05-20.md").read_text()
    assert "# body" in content
    assert "cost_usd: 0.05" in content
