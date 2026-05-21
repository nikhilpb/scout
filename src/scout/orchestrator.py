from __future__ import annotations

import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from scout.config import load_all_topics, load_global_config
from scout.paths import DataPaths
from scout.scheduler import select_due
from scout.state import read_state

log = logging.getLogger("scout.orchestrator")


def tick(data: DataPaths) -> int:
    topics = load_all_topics(data.topics_dir)
    global_cfg = load_global_config(data.config_path)
    now = datetime.now(timezone.utc)
    states = {slug: read_state(slug, data.state_dir) for slug in topics}
    topic_cfgs = {s: t.config for s, t in topics.items()}
    due = select_due(topic_cfgs, states, now)
    print(f"{len(topics)} evaluated, {len(due)} due")
    if not due:
        return 0
    cap = global_cfg.scheduler.max_concurrent_workers
    results: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=cap) as ex:
        futures = {
            ex.submit(_spawn_run, slug, data): slug
            for slug in sorted(due)
        }
        for fut in as_completed(futures):
            slug = futures[fut]
            results[slug] = fut.result()
    ok = sum(1 for r in results.values() if r == 0)
    fail = len(results) - ok
    print(f"{len(results)} spawned, {ok} succeeded, {fail} failed")
    return 0 if fail == 0 else 1


def _spawn_run(slug: str, data: DataPaths) -> int:
    cmd = [
        sys.executable, "-m", "scout",
        "--data-dir", str(data.root),
        "run", "--topic", slug,
    ]
    proc = subprocess.run(cmd)
    return proc.returncode
