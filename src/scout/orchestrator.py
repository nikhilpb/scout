from __future__ import annotations

import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from scout.config import load_all_topics, load_global_config
from scout.scheduler import select_due
from scout.state import read_state

log = logging.getLogger("scout.orchestrator")


def tick(repo_dir: Path) -> int:
    topics = load_all_topics(repo_dir / "topics")
    global_cfg = load_global_config(repo_dir / "scout.toml")
    state_dir = repo_dir / "state"
    now = datetime.now(timezone.utc)
    states = {slug: read_state(slug, state_dir) for slug in topics}
    topic_cfgs = {s: t.config for s, t in topics.items()}
    due = select_due(topic_cfgs, states, now)
    print(f"{len(topics)} evaluated, {len(due)} due")
    if not due:
        return 0
    cap = global_cfg.scheduler.max_concurrent_workers
    results: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=cap) as ex:
        futures = {
            ex.submit(_spawn_run, slug, repo_dir): slug
            for slug in sorted(due)
        }
        for fut in as_completed(futures):
            slug = futures[fut]
            results[slug] = fut.result()
    ok = sum(1 for r in results.values() if r == 0)
    fail = len(results) - ok
    print(f"{len(results)} spawned, {ok} succeeded, {fail} failed")
    return 0 if fail == 0 else 1


def _spawn_run(slug: str, repo_dir: Path) -> int:
    cmd = [sys.executable, "-m", "scout", "run", "--topic", slug]
    proc = subprocess.run(cmd, cwd=repo_dir)
    return proc.returncode
