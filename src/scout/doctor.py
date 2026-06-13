from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from scout.paths import DataPaths
from scout.trajectory import read_records


def _parse_ts(value) -> datetime | None:
    """Parse a record `ts` into an aware UTC datetime; None if unparseable.

    A naive timestamp (no offset) is assumed UTC, so it can be compared against
    the aware cutoff without raising.
    """
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _run_time(records: list[dict]) -> datetime | None:
    """The run's start time, from the `run` header's ts (fallback: any ts)."""
    for rec in records:
        if rec.get("type") == "run":
            return _parse_ts(rec.get("ts"))
    for rec in records:
        ts = _parse_ts(rec.get("ts"))
        if ts is not None:
            return ts
    return None


def doctor(data: DataPaths) -> int:
    traj_dir = data.trajectories_dir
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    per_topic: dict[str, dict] = defaultdict(
        lambda: {"ok": 0, "failed": 0, "last_error": None, "cost": 0.0}
    )
    if not traj_dir.exists():
        print("no trajectories/")
        return 0
    for topic_dir in sorted(traj_dir.iterdir()):
        if not topic_dir.is_dir():
            continue
        for f in sorted(topic_dir.glob("*.jsonl")):
            records = read_records(f)
            ts = _run_time(records)
            if ts is None or ts < cutoff:
                continue
            result = next((r for r in records if r.get("type") == "result"), None)
            if result is None:
                continue
            status = result.get("status", "?")
            key = "ok" if status == "ok" else "failed"
            per_topic[topic_dir.name][key] += 1
            if key == "failed":
                per_topic[topic_dir.name]["last_error"] = result.get("reason")
            c = (result.get("usage") or {}).get("cost_usd")
            if isinstance(c, (int, float)):
                per_topic[topic_dir.name]["cost"] += c
    print(f"{'topic':20} {'ok':>4} {'fail':>4} {'cost_usd':>10}  last_error")
    print("-" * 60)
    for slug, s in sorted(per_topic.items()):
        error = s["last_error"] or ""
        print(
            f"{slug:20} {s['ok']:>4} {s['failed']:>4} {s['cost']:>10.4f}  {error}"
        )
    return 0
