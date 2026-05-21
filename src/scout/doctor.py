from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


def doctor(repo_dir: Path) -> int:
    logs_dir = repo_dir / "logs"
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    per_topic: dict[str, dict] = defaultdict(
        lambda: {"ok": 0, "failed": 0, "last_error": None, "cost": 0.0}
    )
    if not logs_dir.exists():
        print("no logs/")
        return 0
    for topic_dir in sorted(logs_dir.iterdir()):
        if not topic_dir.is_dir():
            continue
        for f in sorted(topic_dir.glob("*.jsonl")):
            try:
                ts = datetime.strptime(f.stem, "%Y-%m-%d-%H%M%S").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if ts < cutoff:
                continue
            for line in f.read_text().splitlines():
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("event") == "run_end":
                    status = ev.get("status", "?")
                    key = "ok" if status == "ok" else "failed"
                    per_topic[topic_dir.name][key] += 1
                    if key == "failed":
                        per_topic[topic_dir.name]["last_error"] = ev.get("reason")
                    c = ev.get("cost_usd")
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
