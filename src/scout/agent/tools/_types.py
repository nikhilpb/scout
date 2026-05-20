from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, FrozenSet

Handler = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ToolImpl:
    name: str
    description: str
    input_schema: dict[str, Any]
    runner_compat: FrozenSet[str]
    default_enabled: bool
    handler: Handler


@dataclass
class RunContext:
    slug: str
    output_dir: Path
    logs_dir: Path
    now: datetime
    # populated by runner before invoking tools
    runlog: object | None = None
