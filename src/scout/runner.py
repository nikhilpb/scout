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
    """Render a run timestamp for prompt injection — UTC, minute precision.

    A naive datetime is assumed to be UTC (mirroring the scheduler's coercion),
    not the host's local zone, so a hand-edited or legacy state timestamp
    without an offset can't shift a window boundary. Seconds are dropped: cron
    granularity makes minute precision sufficient for window bounds.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def apply_time_window(
    body: str, *, now: datetime, last_run: Optional[datetime]
) -> str:
    """Substitute the run-window placeholders — shared by every runner.

    - ``{{now}}`` — this run's start time (UTC).
    - ``{{last_run}}`` — the previous *successful* run's time (UTC), or a
      cold-start marker when the topic has no successful run yet. Sourcing this
      from the last success (the worker passes ``state.last_success_run``), not
      the last attempt, keeps the window gap-free across failures.
    - ``{{cadence_window}}`` — a human phrase describing that same window, for
      templates (e.g. the shipped ``briefing``/``headlines``/``sectioned``
      prompts) that want prose rather than raw bounds.

    Placeholders a prompt does not use are left untouched (the replaces are
    no-ops), so this is safe for every topic and runner.
    """
    now_s = format_run_time(now)
    if last_run is not None:
        last_s = format_run_time(last_run)
        cadence = f"since the last run at {last_s}, through {now_s}"
    else:
        # No defensible concrete lower bound exists on a cold start — inventing
        # one would reintroduce the arbitrary look-back this feature removes.
        # `{{cadence_window}}` stays grammatical; a prompt using raw `{{last_run}}`
        # as a hard bound should branch on this marker (see README).
        last_s = "(no previous run — first run for this topic)"
        cadence = f"this topic's first run (covering up to {now_s})"
    return (
        body.replace("{{now}}", now_s)
        .replace("{{last_run}}", last_s)
        .replace("{{cadence_window}}", cadence)
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
