from datetime import datetime, timezone
from pathlib import Path

import pytest

from scout.config import LoadedTopic, TopicConfig
from scout.runlog import RunLog
from scout.runner import Limits, Paths, make_runner
from tests.smoke.conftest import requires_google_key


@pytest.mark.smoke
@requires_google_key
def test_builtin_against_gemini_flash_lite(tmp_path):
    topic = LoadedTopic(
        slug="smoke",
        path=Path("topics/smoke.yaml"),
        config=TopicConfig(
            title="Smoke",
            description="A smoke test topic.",
            cadence="0 * * * *",
            model="gemini/gemini-2.5-flash",
            prompt={"inline": (
                "Produce a one-paragraph markdown digest stating exactly this: "
                "'Smoke test ran successfully.' Then immediately call write_digest "
                "with that markdown body and stop."
            )},
            tools=["write_digest"],
        ),
    )
    output_dir = tmp_path / "output"
    logs_dir = tmp_path / "logs"
    now = datetime(2026, 5, 20, 7, 0, 0, tzinfo=timezone.utc)
    runner = make_runner("builtin")
    with RunLog("smoke", logs_dir, now=now) as rl:
        result = runner.execute(
            topic,
            Paths(output_dir=output_dir, logs_dir=logs_dir),
            Limits(timeout_seconds=60),
            run_log=rl, now=now,
        )
    assert result.status == "ok", f"unexpected: {result.status} {result.reason}"
    p = output_dir / "smoke" / "2026-05-20.md"
    assert p.exists()
    content = p.read_text()
    assert content.startswith("---\n")
    assert "runner: builtin" in content
    assert "model: gemini/gemini-2.5-flash" in content
    assert "input: 0" not in content
    body = content.split("---", 2)[2].strip()
    assert len(body) > 5
