from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from scout.config import load_global_config, load_topic
from scout.git_publish import PushDeferred, publish
from scout.runlog import RunLog
from scout.runner import Limits, Paths, make_runner
from scout.scheduler import is_due
from scout.state import TopicState, acquire_lock, read_state, write_state_atomic

log = logging.getLogger("scout.worker")


def run_topic(
    slug: str,
    *,
    repo_dir: Path,
    force: bool = False,
    dry_run: bool = False,
) -> int:
    topic_path = repo_dir / "topics" / f"{slug}.yaml"
    loaded = load_topic(topic_path)
    global_cfg = load_global_config(repo_dir / "scout.toml")
    state_dir = repo_dir / "state"
    logs_dir = repo_dir / "logs"
    output_dir = repo_dir / "output"

    now = datetime.now(timezone.utc)
    state = read_state(slug, state_dir)
    if not force and not is_due(loaded.config, state, now):
        print(f"{slug}: not due")
        return 0

    with acquire_lock(slug, state_dir) as got:
        if not got:
            print(f"{slug}: skipped (locked)")
            return 0
        runner_name = loaded.config.runner
        runner = make_runner(runner_name)
        timeout = (
            loaded.config.limits.timeout_seconds
            if loaded.config.limits and loaded.config.limits.timeout_seconds
            else global_cfg.defaults.timeout_seconds
        )
        try:
            with RunLog(slug, logs_dir, now=now) as rl:
                result = runner.execute(
                    loaded,
                    Paths(output_dir=output_dir, logs_dir=logs_dir),
                    Limits(timeout_seconds=timeout),
                    run_log=rl, now=now,
                )
        except Exception as e:
            log.exception("runner crashed")
            write_state_atomic(slug, state_dir, TopicState(
                last_run=now, last_status="failed",
                last_error=f"runner_crashed: {e}", last_duration_seconds=0.0,
            ))
            return 1

        write_state_atomic(slug, state_dir, TopicState(
            last_run=now,
            last_status=result.status,
            last_error=result.reason if result.status == "failed" else None,
            last_duration_seconds=result.duration_seconds,
        ))
        if result.status != "ok" or dry_run:
            msg = f"{slug}: {result.status}"
            if result.reason:
                msg += f" ({result.reason})"
            if dry_run and result.status == "ok":
                msg += " (dry-run; not published)"
            print(msg)
            return 0 if result.status == "ok" else 1
        try:
            publish(
                repo_dir=repo_dir,
                file_path=result.output_path,
                slug=slug,
                date_str=now.strftime("%Y-%m-%d"),
                git_cfg=global_cfg.git,
                state_dir=state_dir,
            )
            print(f"{slug}: ok (published)")
        except PushDeferred as e:
            log.warning("push deferred: %s", e)
            print(f"{slug}: ok (push deferred)")
        return 0
