from datetime import datetime, timezone

from scout.agent.tools._types import RunContext
from scout.agent.tools.write_digest import handler as write_digest_handler


def test_write_digest_creates_file(tmp_path):
    ctx = RunContext(
        slug="ai-research",
        output_dir=tmp_path,
        logs_dir=tmp_path,
        now=datetime(2026, 5, 20, 7, tzinfo=timezone.utc),
    )
    r = write_digest_handler(ctx, markdown_body="# Hello")
    assert r["ok"] is True
    p = tmp_path / "ai-research" / "2026-05-20.md"
    assert p.exists()
    assert p.read_text() == "# Hello"
