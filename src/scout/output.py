from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Union

import yaml


@dataclass(frozen=True)
class DigestRecord:
    topic: str
    date: str  # YYYY-MM-DD
    runner: str
    model: Union[str, None]              # "unknown" for CLI runners
    duration_seconds: float
    tool_calls: Union[dict[str, int], str]
    tokens: Union[dict[str, int], str]
    cost_usd: Union[float, str]


def compose_digest(rec: DigestRecord, body: str) -> str:
    data = {
        "topic": rec.topic,
        "date": rec.date,
        "runner": rec.runner,
        "model": rec.model,
        "duration_seconds": rec.duration_seconds,
        "tool_calls": rec.tool_calls,
        "tokens": rec.tokens,
        "cost_usd": rec.cost_usd,
    }
    fm = yaml.safe_dump(data, sort_keys=False, default_flow_style=None).strip()
    return f"---\n{fm}\n---\n\n{body}"


def pick_output_path(slug: str, output_dir: Path, now: datetime) -> Path:
    date_str = now.strftime("%Y-%m-%d")
    topic_dir = output_dir / slug
    topic_dir.mkdir(parents=True, exist_ok=True)
    candidate = topic_dir / f"{date_str}.md"
    if not candidate.exists():
        return candidate
    return topic_dir / f"{date_str}-{now.strftime('%H%M%S')}.md"
