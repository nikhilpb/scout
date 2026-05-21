from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from croniter import croniter

from scout.config import TopicConfig
from scout.state import TopicState


def is_due(cfg: TopicConfig, state: Optional[TopicState], now: datetime) -> bool:
    if state is None:
        return True
    itr = croniter(cfg.cadence, state.last_run)
    next_due = itr.get_next(datetime)
    if next_due.tzinfo is None:
        next_due = next_due.replace(tzinfo=timezone.utc)
    return now >= next_due


def select_due(
    topics: dict[str, TopicConfig],
    states: dict[str, Optional[TopicState]],
    now: datetime,
) -> set[str]:
    return {slug for slug, cfg in topics.items() if is_due(cfg, states.get(slug), now)}
