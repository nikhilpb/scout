from __future__ import annotations

import fcntl
import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Literal, Optional

log = logging.getLogger("scout.state")


@dataclass(frozen=True)
class TopicState:
    last_run: datetime
    last_status: Literal["ok", "failed"]
    last_error: Optional[str]
    last_duration_seconds: float
    # Time of the last *successful* run. `last_run` advances on every attempt
    # (including failures, which is what the scheduler wants for cadence), but a
    # gap-free coverage window must key off the last success — otherwise a failed
    # run shrinks the next window and silently drops the slice it owed.
    last_success_run: Optional[datetime] = None


def _state_path(slug: str, state_dir: Path) -> Path:
    return state_dir / f"{slug}.json"


def read_state(slug: str, state_dir: Path) -> Optional[TopicState]:
    p = _state_path(slug, state_dir)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        raw_success = data.get("last_success_run")
        if raw_success is not None:
            last_success_run = datetime.fromisoformat(raw_success)
        elif data["last_status"] == "ok":
            # Migrate legacy state written before this field existed: if the last
            # recorded run succeeded, it was the last success.
            last_success_run = datetime.fromisoformat(data["last_run"])
        else:
            last_success_run = None
        return TopicState(
            last_run=datetime.fromisoformat(data["last_run"]),
            last_status=data["last_status"],
            last_error=data.get("last_error"),
            last_duration_seconds=float(data["last_duration_seconds"]),
            last_success_run=last_success_run,
        )
    except Exception as e:
        log.warning("state for %s is corrupt: %s", slug, e)
        return None


def write_state_atomic(slug: str, state_dir: Path, state: TopicState) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    p = _state_path(slug, state_dir)
    tmp = p.with_suffix(p.suffix + ".tmp")
    payload = {
        "last_run": state.last_run.isoformat(),
        "last_status": state.last_status,
        "last_error": state.last_error,
        "last_duration_seconds": state.last_duration_seconds,
        "last_success_run": (
            state.last_success_run.isoformat() if state.last_success_run else None
        ),
    }
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, p)


@contextmanager
def acquire_lock(slug: str, state_dir: Path) -> Iterator[bool]:
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / f"{slug}.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield True
            fcntl.flock(fd, fcntl.LOCK_UN)
        except BlockingIOError:
            yield False
    finally:
        os.close(fd)
