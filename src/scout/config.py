from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Defaults:
    runner: str = "builtin"
    model: str = "anthropic/claude-sonnet-4-6"
    timeout_seconds: int = 300


@dataclass(frozen=True)
class Scheduler:
    max_concurrent_workers: int = 3


@dataclass(frozen=True)
class Git:
    author_name: str = "Scout"
    author_email: str = "scout@localhost"
    remote: str = "origin"
    branch: str = "main"


@dataclass(frozen=True)
class GlobalConfig:
    defaults: Defaults
    scheduler: Scheduler
    git: Git


def load_global_config(path: Path) -> GlobalConfig:
    if not path.exists():
        return GlobalConfig(Defaults(), Scheduler(), Git())
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML in {path}: {e}") from e
    return GlobalConfig(
        defaults=Defaults(**data.get("defaults", {})),
        scheduler=Scheduler(**data.get("scheduler", {})),
        git=Git(**data.get("git", {})),
    )
