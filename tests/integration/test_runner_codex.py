import os
import stat
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scout.config import LoadedTopic, TopicConfig
from scout.runlog import RunLog
from scout.runner import Limits, Paths, make_runner


def _install_fake_codex(bindir: Path, body_to_write: str, file_rel: str):
    bindir.mkdir(parents=True, exist_ok=True)
    script = bindir / "codex"
    script.write_text(textwrap.dedent(f"""\
        #!/bin/sh
        # ignore prompt argv; just produce the file
        mkdir -p "$(dirname {file_rel})"
        printf %s {body_to_write!r} > {file_rel}
    """))
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.mark.integration
def test_codex_runner_invokes_cli(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    out_dir = tmp_path / "output"
    logs_dir = tmp_path / "logs"
    now = datetime(2026, 5, 20, 7, tzinfo=timezone.utc)
    _install_fake_codex(bindir, body_to_write="# from-codex", file_rel="ai/2026-05-20.md")

    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    topic = LoadedTopic(
        slug="ai", path=Path("topics/ai.yaml"),
        config=TopicConfig(
            title="AI", description="AI research.",
            cadence="0 7 * * *", runner="codex",
            prompt={"template": "briefing"},
        ),
    )
    runner = make_runner("codex")
    with RunLog("ai", logs_dir, now=now) as rl:
        result = runner.execute(
            topic,
            Paths(output_dir=out_dir, logs_dir=logs_dir),
            Limits(timeout_seconds=10),
            run_log=rl, now=now,
        )
    assert result.status == "ok"
    p = out_dir / "ai" / "2026-05-20.md"
    assert p.exists()
    content = p.read_text()
    assert "runner: codex" in content
    assert "model: unknown" in content
    assert "# from-codex" in content
