from __future__ import annotations

import logging
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Optional

import yaml
from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

log = logging.getLogger("scout.config")

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


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class LoadedTopic:
    slug: str
    path: Path
    config: TopicConfig


def load_topic(path: Path) -> LoadedTopic:
    if path.suffix != ".yaml":
        raise ConfigError(f"{path}: expected .yaml extension")
    slug = path.stem
    if not SLUG_RE.match(slug):
        raise ConfigError(
            f"{path}: invalid slug '{slug}' — must match {SLUG_RE.pattern}"
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: malformed YAML: {e}") from e
    try:
        cfg = TopicConfig(**data)
    except Exception as e:
        raise ConfigError(f"{path}: {e}") from e
    if cfg.runner != "builtin" and cfg.tools is not None:
        log.warning(
            "%s: `tools` field is ignored when runner=%s (uses its own tool set)",
            path,
            cfg.runner,
        )
    return LoadedTopic(slug=slug, path=path, config=cfg)


def load_all_topics(topics_dir: Path) -> dict[str, LoadedTopic]:
    out: dict[str, LoadedTopic] = {}
    if not topics_dir.exists():
        return out
    for p in sorted(topics_dir.glob("*.yaml")):
        try:
            loaded = load_topic(p)
            out[loaded.slug] = loaded
        except ConfigError as e:
            log.error("skipping %s: %s", p.name, e)
    return out
