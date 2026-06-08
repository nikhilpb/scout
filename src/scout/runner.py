from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional, Protocol

from scout.config import LoadedTopic
from scout.runlog import RunLog


@dataclass(frozen=True)
class Paths:
    output_dir: Path
    logs_dir: Path


@dataclass(frozen=True)
class Limits:
    timeout_seconds: float


@dataclass(frozen=True)
class RunResult:
    status: Literal["ok", "failed"]
    reason: Optional[str]
    output_path: Optional[Path]
    duration_seconds: float
    summary: dict


class Runner(Protocol):
    def execute(
        self,
        topic: LoadedTopic,
        paths: Paths,
        limits: Limits,
        *,
        run_log: RunLog,
        now: datetime,
        last_run: Optional[datetime] = None,
    ) -> RunResult: ...


def format_run_time(dt: datetime) -> str:
    """Render a run timestamp for prompt injection — UTC, minute precision."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def apply_time_window(
    body: str, *, now: datetime, last_run: Optional[datetime]
) -> str:
    """Substitute the ``{{now}}`` / ``{{last_run}}`` prompt placeholders.

    ``{{now}}`` is this run's start time; ``{{last_run}}`` is the previous run's
    time, or a cold-start sentinel when the topic has never run. Both are UTC.
    A topic prompt can use these to scope its digest strictly to the window
    between the last run and now. Placeholders that a prompt does not use are
    left untouched (the replaces are no-ops), so this is safe for every topic.
    """
    last = (
        format_run_time(last_run)
        if last_run is not None
        else "(no previous run — this is the first run for this topic)"
    )
    return body.replace("{{now}}", format_run_time(now)).replace(
        "{{last_run}}", last
    )


def make_runner(name: str) -> Runner:
    if name == "builtin":
        from scout.runners.builtin import BuiltinRunner

        return BuiltinRunner()
    if name == "claude-code":
        from scout.runners.claude_code import ClaudeCodeRunner

        return ClaudeCodeRunner()
    if name == "codex":
        from scout.runners.codex import CodexRunner

        return CodexRunner()
    raise ValueError(f"unknown runner: {name}")
