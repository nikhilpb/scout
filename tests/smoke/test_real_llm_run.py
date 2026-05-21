import json
import os
import subprocess
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scout.state import read_state
from tests.smoke.conftest import requires_google_key


def _init_git(d: Path):
    subprocess.run(["git", "init", "-b", "main", str(d)], check=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(
        ["git", "-C", str(d), "commit", "--allow-empty", "-m", "init"], check=True, env=env
    )


@pytest.mark.smoke
@requires_google_key
def test_scout_run_dry_run_against_gemini(tmp_path, monkeypatch):
    _init_git(tmp_path)

    # minimal scout.toml so the worker resolves defaults
    (tmp_path / "scout.toml").write_text(
        textwrap.dedent("""
        [defaults]
        runner = "builtin"
        model = "gemini/gemini-2.5-flash"
        timeout_seconds = 60

        [git]
        author_name = "Scout"
        author_email = "scout@localhost"
        remote = "origin"
        branch = "main"
    """)
    )
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "smoke.yaml").write_text(
        textwrap.dedent("""
        title: Smoke
        description: A smoke test topic.
        cadence: "0 * * * *"
        model: "gemini/gemini-2.5-flash"
        prompt:
          inline: |
            Produce a one-paragraph markdown digest stating exactly:
            'Smoke test ran successfully.' Then immediately call write_digest
            with that markdown body and stop.
        tools:
          - write_digest
    """)
    )
    (tmp_path / "prompts").mkdir()
    monkeypatch.chdir(tmp_path)

    from scout.cli import main

    rc = main(["run", "--topic", "smoke", "--dry-run", "--force"])
    assert rc == 0, f"scout run failed with rc={rc}"

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p = tmp_path / "output" / "smoke" / f"{today}.md"
    assert p.exists()
    content = p.read_text()
    assert "runner: builtin" in content
    assert "model: gemini/gemini-2.5-flash" in content
    assert "write_digest: 1" in content

    st = read_state("smoke", tmp_path / "state")
    assert st is not None and st.last_status == "ok"

    # dry-run did NOT commit
    log = subprocess.check_output(["git", "-C", str(tmp_path), "log", "--oneline"]).decode()
    assert log.count("\n") == 1, f"expected only init commit, got: {log!r}"

    jsonl_files = list((tmp_path / "logs" / "smoke").glob("*.jsonl"))
    assert len(jsonl_files) == 1
    events = [json.loads(line) for line in jsonl_files[0].read_text().splitlines()]
    names = [e["event"] for e in events]
    assert "run_start" in names
    assert "llm_turn" in names
    assert "run_end" in names
