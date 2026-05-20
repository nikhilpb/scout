import os
import stat
import subprocess
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest


def init_repo(d: Path):
    subprocess.run(["git", "init", "-b", "main", str(d)], check=True)
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "-C", str(d), "commit", "--allow-empty", "-m", "init"],
                   check=True, env=env)


@pytest.mark.integration
def test_dry_run_writes_no_commit(tmp_path, monkeypatch):
    init_repo(tmp_path)
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "ai.yaml").write_text(textwrap.dedent("""
        title: AI
        description: d
        cadence: "0 * * * *"
        runner: claude-code
        prompt: {template: briefing}
    """))
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "briefing.md").write_text("brief")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "claude"
    script.write_text(textwrap.dedent("""\
        #!/bin/sh
        mkdir -p ai && echo "# hi" > ai/$(date -u +%Y-%m-%d).md
    """))
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.chdir(tmp_path)

    from scout.cli import main
    assert main(["run", "--topic", "ai", "--dry-run", "--force"]) == 0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert (tmp_path / "output" / "ai" / f"{today}.md").exists()
    log = subprocess.check_output(["git", "-C", str(tmp_path), "log", "--oneline"]).decode()
    assert log.count("\n") == 1  # only the init commit
