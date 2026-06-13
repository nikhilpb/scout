"""Read-side model of the data repo's ``trajectories/`` tree for the dashboard.

A trajectory is ``trajectories/<slug>/<run-id>.jsonl`` in the ``scout.trajectory/1``
schema (see ``docs/trajectory-schema.md``): a ``run`` header, body records
(message / tool_call / tool_result / artifact), and a terminal ``result``. This
module parses those files into view models; it never writes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from scout.paths import DataPaths
from scout.trajectory import read_records

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# A run id is a ULID (26 Crockford chars); allow the broader set so hand-made or
# legacy ids still resolve, but forbid dots/slashes so a name can't traverse out.
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class RunSummary:
    slug: str
    run_id: str
    started_at: str
    pretty_started: str
    runner: str
    model: str
    status: str  # ok / failed / running
    reason: Optional[str]
    duration_seconds: Optional[float]
    cost_usd: Optional[float]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    num_turns: Optional[int]
    tool_calls: dict
    title: Optional[str]


@dataclass(frozen=True)
class TrajectoryDoc:
    summary: RunSummary
    header: dict
    records: list[dict]
    result: Optional[dict]


@dataclass(frozen=True)
class TopicRuns:
    slug: str
    title: str
    runs: list[RunSummary]

    @property
    def latest(self) -> Optional[RunSummary]:
        return self.runs[0] if self.runs else None


def _summary_records(path: Path) -> list[dict]:
    """Just the `run` header + terminal `result` — for cheap list views.

    Parses only the first line and the last `result` line instead of the whole
    transcript, so the index/topic pages don't pay to JSON-decode every message
    and (possibly large) tool result of every run.
    """
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    out: list[dict] = []
    if lines:
        try:
            head = json.loads(lines[0])
            if isinstance(head, dict):
                out.append(head)
        except json.JSONDecodeError:
            pass
        for ln in reversed(lines):
            try:
                rec = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict) and rec.get("type") == "result":
                out.append(rec)
                break
    return out


def _pretty_ts(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return iso or "—"
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt.tzinfo is None else (
        dt.astimezone().strftime("%Y-%m-%d %H:%M %Z")
    )


def _summary_from(slug: str, run_id: str, records: list[dict]) -> RunSummary:
    header = next((r for r in records if r.get("type") == "run"), {})
    result = next((r for r in records if r.get("type") == "result"), None)
    usage = (result or {}).get("usage")
    usage = usage if isinstance(usage, dict) else {}
    # Coerce to a string so a malformed numeric `ts` can't break sorting/formatting.
    started = header.get("ts", "")
    started = started if isinstance(started, str) else str(started)
    tool_calls = (result or {}).get("tool_calls")
    return RunSummary(
        slug=slug,
        run_id=run_id,
        started_at=started,
        pretty_started=_pretty_ts(started),
        runner=header.get("runner", "—"),
        model=header.get("model", "—"),
        status=(result or {}).get("status", "running"),
        reason=(result or {}).get("reason"),
        duration_seconds=(result or {}).get("duration_seconds"),
        cost_usd=usage.get("cost_usd"),
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        num_turns=(result or {}).get("num_turns"),
        tool_calls=tool_calls if isinstance(tool_calls, dict) else {},
        title=header.get("title"),
    )


def _safe_topic_dir(data: DataPaths, slug: str) -> Optional[Path]:
    if not SLUG_RE.match(slug):
        return None
    d = data.trajectories_dir / slug
    return d if d.is_dir() else None


def list_runs(data: DataPaths, slug: str) -> list[RunSummary]:
    topic_dir = _safe_topic_dir(data, slug)
    if topic_dir is None:
        return []
    summaries = []
    for p in topic_dir.glob("*.jsonl"):
        if not p.is_file():
            continue
        summaries.append(_summary_from(slug, p.stem, _summary_records(p)))
    # ULID run ids sort lexicographically by time; newest first.
    return sorted(summaries, key=lambda s: s.run_id, reverse=True)


def _title_for(data: DataPaths, slug: str, runs: list[RunSummary]) -> str:
    for r in runs:
        if r.title:
            return r.title
    return slug.replace("-", " ").capitalize()


def list_topics(data: DataPaths) -> list[TopicRuns]:
    if not data.trajectories_dir.is_dir():
        return []
    topics = []
    for child in sorted(data.trajectories_dir.iterdir()):
        if not child.is_dir() or not SLUG_RE.match(child.name):
            continue
        runs = list_runs(data, child.name)
        if not runs:
            continue
        topics.append(
            TopicRuns(slug=child.name, title=_title_for(data, child.name, runs), runs=runs)
        )
    return topics


def recent_runs(topics: list[TopicRuns], limit: int = 50) -> list[RunSummary]:
    merged = [r for t in topics for r in t.runs]
    merged.sort(key=lambda s: (s.started_at, s.run_id), reverse=True)
    return merged[:limit]


def load_trajectory(data: DataPaths, slug: str, run_id: str) -> Optional[TrajectoryDoc]:
    if not SLUG_RE.match(slug) or not RUN_ID_RE.match(run_id):
        return None
    path = data.trajectories_dir / slug / f"{run_id}.jsonl"
    # Defend against symlink / traversal: the resolved file must live in the dir.
    try:
        resolved = path.resolve()
        topic_root = (data.trajectories_dir / slug).resolve()
    except OSError:
        return None
    if topic_root not in resolved.parents or not path.is_file():
        return None
    records = read_records(path)
    if not records:
        return None
    header = next((r for r in records if r.get("type") == "run"), {})
    result = next((r for r in records if r.get("type") == "result"), None)
    return TrajectoryDoc(
        summary=_summary_from(slug, run_id, records),
        header=header,
        records=records,
        result=result,
    )
