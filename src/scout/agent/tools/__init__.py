from __future__ import annotations

from typing import Mapping

from scout.agent.tools._types import ToolImpl

_REGISTRY: dict[str, ToolImpl] = {}


def register(tool: ToolImpl) -> None:
    _REGISTRY[tool.name] = tool


def registry() -> Mapping[str, ToolImpl]:
    return dict(_REGISTRY)


# Tools self-register at import time.
from scout.agent.tools import browser as _browser  # noqa: F401,E402
from scout.agent.tools import fetch_url as _fetch_url  # noqa: F401,E402
from scout.agent.tools import read_history as _read_history  # noqa: F401,E402
from scout.agent.tools import web_search as _web_search  # noqa: F401,E402
from scout.agent.tools import write_digest as _write_digest  # noqa: F401,E402
