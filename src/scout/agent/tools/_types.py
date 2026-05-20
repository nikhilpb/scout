from __future__ import annotations

from dataclasses import dataclass
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
