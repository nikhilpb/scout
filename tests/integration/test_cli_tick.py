import os
import stat
import textwrap
from datetime import datetime, timezone

import pytest


@pytest.mark.integration
def test_tick_runs_due_topics(tmp_path, monkeypatch):
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "ai.yaml").write_text(textwrap.dedent("""
        title: AI
        description: d
        cadence: "0 * * * *"
        runner: claude-code
        prompt: {template: briefing}
    """))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "claude"
    script.write_text(textwrap.dedent("""\
        #!/bin/sh
        mkdir -p ai && echo "# hi" > ai/$(date -u +%Y-%m-%d).md
    """))
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("SCOUT_DATA_DIR", str(tmp_path))

    from scout.cli import main
    assert main(["tick"]) == 0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert (tmp_path / "output" / "ai" / f"{today}.md").exists()
