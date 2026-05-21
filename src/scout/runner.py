from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
    ) -> RunResult: ...


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
