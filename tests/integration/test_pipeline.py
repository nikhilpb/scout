import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scout.agent.llm import Response, ToolCall
from scout.runners import builtin as br
from scout.worker import run_topic
from tests.fakes.llm import FakeLLMClient


@pytest.mark.integration
def test_full_pipeline(tmp_path, monkeypatch):
    # Set up a temp bare remote and a working repo populated with the scout source
    remote = tmp_path / "remote.git"
    work = tmp_path / "scout-repo"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True)

    # Copy the scout source tree into the work dir (excluding .git, .venv, output, state, logs)
    repo_root = Path(__file__).resolve().parent.parent.parent
    shutil.copytree(
        repo_root, work,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", "__pycache__", "logs", "state", "output", ".pytest_cache",
            ".ruff_cache", "*.egg-info", "dist",
        ),
    )
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-b", "main", str(work)], check=True)
    subprocess.run(["git", "-C", str(work), "remote", "add", "origin", str(remote)], check=True)
    subprocess.run(["git", "-C", str(work), "add", "."], check=True)
    subprocess.run(["git", "-C", str(work), "commit", "-m", "init"], check=True, env=env)
    subprocess.run(["git", "-C", str(work), "push", "-u", "origin", "main"], check=True)

    # Drop in the smoke topic fixture
    (work / "topics").mkdir(exist_ok=True)
    shutil.copy(
        Path(__file__).parent.parent / "fixtures" / "topics" / "smoke.yaml",
        work / "topics" / "smoke.yaml",
    )

    # Script the LLM: a single call to write_digest
    script = [
        Response(
            text=None,
            tool_calls=[ToolCall(
                "1", "write_digest",
                {"markdown_body": "# Smoke\n\nHello."},
            )],
            input_tokens=10, output_tokens=2, cost_usd=0.001,
        ),
    ]
    fake = FakeLLMClient(script)
    monkeypatch.setattr(br, "default_llm_client", lambda: fake)

    monkeypatch.chdir(work)
    rc = run_topic("smoke", repo_dir=work, force=True)
    assert rc == 0

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p = work / "output" / "smoke" / f"{today}.md"
    assert p.exists()
    content = p.read_text()
    assert "# Smoke" in content
    assert content.startswith("---\n")

    from scout.state import read_state
    st = read_state("smoke", work / "state")
    assert st is not None
    assert st.last_status == "ok"

    # Bare remote received the commit
    remote_log = subprocess.check_output(["git", "-C", str(remote), "log", "--oneline"]).decode()
    assert "digest(smoke)" in remote_log
