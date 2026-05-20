from __future__ import annotations

from typing import Mapping

from scout.agent.tools._types import ToolImpl

_REGISTRY: dict[str, ToolImpl] = {}


def register(tool: ToolImpl) -> None:
    _REGISTRY[tool.name] = tool


def registry() -> Mapping[str, ToolImpl]:
    return dict(_REGISTRY)


# Tools self-register at import time. Guard with try/except so this Task 10
# package can be imported before Tasks 11–15 land. Task 15 will remove the
# guards once all five tools are present.
for _name in ("write_digest", "read_history", "fetch_url", "web_search", "browser"):
    try:
        __import__(f"scout.agent.tools.{_name}")
    except ImportError:
        pass
