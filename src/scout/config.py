from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Optional

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


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
        with path.open("rb") as f:
            data = tomllib.load(f)
        return GlobalConfig(
            defaults=Defaults(**data.get("defaults", {})),
            scheduler=Scheduler(**data.get("scheduler", {})),
            git=Git(**data.get("git", {})),
        )
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML in {path}: {e}") from e
    except TypeError as e:
        raise ConfigError(f"unexpected field in {path}: {e}") from e


# Names mirror the builtin runner's tool registry (Task 10).
BUILTIN_TOOLS: frozenset[str] = frozenset(
    {"web_search", "fetch_url", "browser_use", "read_history", "write_digest"}
)
RUNNER_NAMES: frozenset[str] = frozenset({"builtin", "claude-code", "codex"})


class RssSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["rss"]
    url: HttpUrl


class WebSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["web"]
    url: HttpUrl


class SearchSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["search"]
    query: str


Source = Annotated[
    RssSource | WebSource | SearchSource,
    Field(discriminator="type"),
]


class Prompt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template: Optional[str] = None
    inline: Optional[str] = None

    @model_validator(mode="after")
    def exactly_one(self) -> "Prompt":
        present = sum(x is not None for x in (self.template, self.inline))
        if present != 1:
            raise ValueError("exactly one of `template` or `inline` is required")
        return self


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timeout_seconds: Optional[int] = Field(default=None, gt=0)


class TopicConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str
    cadence: str
    sources: list[Source] = Field(default_factory=list)
    runner: Literal["builtin", "claude-code", "codex"] = "builtin"
    model: Optional[str] = None
    prompt: Prompt
    limits: Optional[Limits] = None
    tools: Optional[list[str]] = None

    @model_validator(mode="after")
    def validate_all(self) -> "TopicConfig":
        if not croniter.is_valid(self.cadence):
            raise ValueError(f"invalid cron expression: {self.cadence}")
        if self.runner == "builtin" and not self.model:
            raise ValueError("`model` is required when runner=builtin")
        if self.tools is not None:
            extra = set(self.tools) - BUILTIN_TOOLS
            if extra:
                raise ValueError(f"unknown tool(s): {sorted(extra)}")
        return self
