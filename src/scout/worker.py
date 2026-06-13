from __future__ import annotations

import logging
import socket
from datetime import datetime, timezone
from pathlib import Path

from scout.config import LoadedTopic, load_global_config, load_topic
from scout.paths import DataPaths
from scout.runner import Limits, Paths, make_runner
from scout.scheduler import is_due
from scout.state import TopicState, acquire_lock, read_state, write_state_atomic
from scout.trajectory import TrajectoryWriter, provider_of

log = logging.getLogger("scout.worker")


def _scout_version() -> str:
    try:
        from importlib.metadata import version

        return version("scout")
    except Exception:
        return "unknown"


def _config_snapshot(loaded: LoadedTopic, timeout: float) -> dict:
    cfg = loaded.config
    return {
        "cadence": cfg.cadence,
        "runner": cfg.runner,
        "model": cfg.model,
        "effort": cfg.effort,
        "sources": [s.model_dump(mode="json") for s in cfg.sources],
        "tools": cfg.tools,
        "limits": {"timeout_seconds": timeout},
        "prompt": {
            "template": cfg.prompt.template,
            "inline": cfg.prompt.inline is not None,
        },
    }


def run_topic(
    slug: str,
    *,
    data: DataPaths,
    force: bool = False,
) -> int:
    topic_path = data.topics_dir / f"{slug}.yaml"
    loaded = load_topic(topic_path)
    global_cfg = load_global_config(data.config_path)

    now = datetime.now(timezone.utc)
    state = read_state(slug, data.state_dir)
    if not force and not is_due(loaded.config, state, now):
        print(f"{slug}: not due")
        return 0

    # Window lower bound = the last *successful* run, so a prior failure doesn't
    # leave a coverage gap. Preserved unchanged on failure/crash below.
    prev_success = state.last_success_run if state else None

    with acquire_lock(slug, data.state_dir) as got:
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
        with TrajectoryWriter(slug, data.trajectories_dir, now=now) as tw:
            tw.header(
                topic=slug,
                title=loaded.config.title,
                runner=runner_name,
                runner_version=None,
                scout_version=_scout_version(),
                provider=provider_of(loaded.config.model, runner_name),
                model=loaded.config.model or "unknown",
                effort=loaded.config.effort,
                trigger="manual" if force else "schedule",
                run_window={
                    "since": prev_success.isoformat() if prev_success else None,
                    "until": now.isoformat(),
                },
                config=_config_snapshot(loaded, timeout),
                host={"hostname": socket.gethostname(), "cwd": str(Path.cwd())},
            )
            try:
                result = runner.execute(
                    loaded,
                    Paths(
                        output_dir=data.output_dir,
                        trajectories_dir=data.trajectories_dir,
                    ),
                    Limits(timeout_seconds=timeout),
                    traj=tw, now=now,
                    last_run=prev_success,
                )
            except Exception as e:
                log.exception("runner crashed")
                tw.result(
                    status="failed", duration_seconds=0.0,
                    reason=f"runner_crashed: {e}",
                    error={"type": type(e).__name__, "message": str(e)},
                )
                write_state_atomic(slug, data.state_dir, TopicState(
                    last_run=now, last_status="failed",
                    last_error=f"runner_crashed: {e}", last_duration_seconds=0.0,
                    last_success_run=prev_success,
                ))
                return 1

        write_state_atomic(slug, data.state_dir, TopicState(
            last_run=now,
            last_status=result.status,
            last_error=result.reason if result.status == "failed" else None,
            last_duration_seconds=result.duration_seconds,
            last_success_run=now if result.status == "ok" else prev_success,
        ))
        msg = f"{slug}: {result.status}"
        if result.reason:
            msg += f" ({result.reason})"
        print(msg)
        return 0 if result.status == "ok" else 1
