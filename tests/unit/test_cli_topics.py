import textwrap
from datetime import datetime, timezone

from scout.cli import main
from scout.state import TopicState, write_state_atomic


def test_topics_table(tmp_path, capsys, monkeypatch):
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "ai.yaml").write_text(textwrap.dedent("""
        title: AI
        description: d
        cadence: "0 7 * * *"
        model: m
        prompt: {template: briefing}
    """))
    (tmp_path / "state").mkdir()
    write_state_atomic("ai", tmp_path / "state", TopicState(
        last_run=datetime(2026, 5, 20, 7, tzinfo=timezone.utc),
        last_status="ok", last_error=None, last_duration_seconds=12.3,
    ))
    monkeypatch.chdir(tmp_path)
    assert main(["topics"]) == 0
    out = capsys.readouterr().out
    assert "ai" in out
    assert "0 7 * * *" in out
    assert "ok" in out
