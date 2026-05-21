import os
import subprocess
from pathlib import Path

from scout.config import Git
from scout.git_publish import publish


def init_repos(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "init", "-b", "main", str(work)], check=True)
    subprocess.run(["git", "-C", str(work), "remote", "add", "origin", str(remote)], check=True)
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "-C", str(work), "commit", "--allow-empty", "-m", "init"],
                   check=True, env=env)
    subprocess.run(["git", "-C", str(work), "push", "-u", "origin", "main"], check=True)
    return work, remote


def test_publish_happy_path(tmp_path):
    work, remote = init_repos(tmp_path)
    (work / "out").mkdir()
    f = work / "out" / "x.md"
    f.write_text("hello")
    state_dir = work / "state"
    state_dir.mkdir()
    git_cfg = Git()
    publish(work, f, "x", "2026-05-20", git_cfg, state_dir=state_dir)
    log = subprocess.check_output(["git", "-C", str(work), "log", "--oneline"]).decode()
    assert "digest(x): 2026-05-20" in log
    remote_log = subprocess.check_output(["git", "-C", str(remote), "log", "--oneline"]).decode()
    assert "digest(x):" in remote_log


def test_push_failure_triggers_rebase_retry(tmp_path):
    work, remote = init_repos(tmp_path)
    other = tmp_path / "other"
    subprocess.run(["git", "clone", str(remote), str(other)], check=True)
    (other / "side.md").write_text("side")
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "-C", str(other), "add", "side.md"], check=True)
    subprocess.run(["git", "-C", str(other), "commit", "-m", "side"], check=True, env=env)
    subprocess.run(["git", "-C", str(other), "push", "origin", "main"], check=True)

    (work / "out").mkdir(exist_ok=True)
    f = work / "out" / "y.md"
    f.write_text("y")
    state_dir = work / "state"
    state_dir.mkdir(exist_ok=True)
    publish(work, f, "y", "2026-05-20", Git(), state_dir=state_dir)
    log = subprocess.check_output(["git", "-C", str(remote), "log", "--oneline"]).decode()
    assert "side" in log
    assert "digest(y)" in log
