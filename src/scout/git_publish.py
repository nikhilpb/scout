from __future__ import annotations

import fcntl
import logging
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path

from scout.config import Git

log = logging.getLogger("scout.git_publish")


class PushDeferred(Exception):
    pass


@contextmanager
def _publish_lock(state_dir: Path):
    state_dir.mkdir(parents=True, exist_ok=True)
    p = state_dir / ".publish.lock"
    fd = os.open(p, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _run(cmd: list[str], cwd: Path, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, check=False)


def publish(
    repo_dir: Path,
    file_path: Path,
    slug: str,
    date_str: str,
    git_cfg: Git,
    *,
    state_dir: Path,
) -> None:
    author_env = {
        "GIT_AUTHOR_NAME": git_cfg.author_name,
        "GIT_AUTHOR_EMAIL": git_cfg.author_email,
        "GIT_COMMITTER_NAME": git_cfg.author_name,
        "GIT_COMMITTER_EMAIL": git_cfg.author_email,
    }
    rel = file_path.relative_to(repo_dir).as_posix()
    with _publish_lock(state_dir):
        add = _run(["git", "add", rel], repo_dir)
        if add.returncode != 0:
            raise PushDeferred(f"git add failed: {add.stderr}")
        commit = _run(
            ["git", "commit", "-m", f"digest({slug}): {date_str}"],
            repo_dir, env_extra=author_env,
        )
        if commit.returncode != 0:
            raise PushDeferred(f"git commit failed: {commit.stderr}")

        push = _run(["git", "push", git_cfg.remote, git_cfg.branch], repo_dir)
        if push.returncode == 0:
            return

        log.warning("push failed (%s); attempting pull --rebase + retry", push.stderr.strip())
        rebase = _run(
            ["git", "pull", "--rebase", git_cfg.remote, git_cfg.branch],
            repo_dir, env_extra=author_env,
        )
        if rebase.returncode != 0:
            log.error("pull --rebase failed: %s", rebase.stderr.strip())
            raise PushDeferred("rebase failed; local commit retained")
        push2 = _run(["git", "push", git_cfg.remote, git_cfg.branch], repo_dir)
        if push2.returncode != 0:
            log.error("retry push failed: %s", push2.stderr.strip())
            raise PushDeferred("push still failing after rebase; local commit retained")
