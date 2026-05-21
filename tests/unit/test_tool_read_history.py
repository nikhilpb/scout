from datetime import datetime, timezone

from scout.agent.tools._types import RunContext
from scout.agent.tools.read_history import handler as read_history_handler


def test_returns_empty_when_no_history(tmp_path):
    ctx = RunContext("ai", tmp_path, tmp_path, datetime.now(timezone.utc))
    assert read_history_handler(ctx)["history"] == ""


def test_returns_newest_first(tmp_path):
    d = tmp_path / "ai"
    d.mkdir()
    (d / "2026-05-18.md").write_text("old")
    (d / "2026-05-20.md").write_text("new")
    (d / "2026-05-19.md").write_text("mid")
    ctx = RunContext("ai", tmp_path, tmp_path, datetime.now(timezone.utc))
    out = read_history_handler(ctx, n=2)["history"]
    assert out.index("new") < out.index("mid")
    assert "old" not in out
