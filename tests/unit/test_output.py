from datetime import datetime, timezone

from scout.output import DigestRecord, compose_digest, pick_output_path


def test_compose_includes_frontmatter():
    rec = DigestRecord(
        topic="ai-research",
        date="2026-05-20",
        runner="builtin",
        model="anthropic/claude-sonnet-4-6",
        duration_seconds=38.2,
        tool_calls={"web_search": 3, "fetch_url": 12},
        tokens={"input": 45000, "output": 3200},
        cost_usd=0.18,
    )
    out = compose_digest(rec, "# Hello\n\nBody.")
    assert out.startswith("---\n")
    assert "topic: ai-research" in out
    assert "cost_usd: 0.18" in out
    assert out.endswith("# Hello\n\nBody.")


def test_compose_unknown_for_cli_runner():
    rec = DigestRecord(
        topic="ai-research",
        date="2026-05-20",
        runner="claude-code",
        model="unknown",
        duration_seconds=47.1,
        tool_calls="unknown",
        tokens="unknown",
        cost_usd="unknown",
    )
    out = compose_digest(rec, "body")
    assert "model: unknown" in out
    assert "tool_calls: unknown" in out


def test_pick_path_no_collision(tmp_path):
    now = datetime(2026, 5, 20, 7, 0, 0, tzinfo=timezone.utc)
    p = pick_output_path("ai-research", tmp_path, now)
    assert p == tmp_path / "ai-research" / "2026-05-20.md"


def test_pick_path_collision_adds_time(tmp_path):
    now = datetime(2026, 5, 20, 7, 0, 0, tzinfo=timezone.utc)
    (tmp_path / "ai-research").mkdir(parents=True)
    (tmp_path / "ai-research" / "2026-05-20.md").write_text("x")
    p = pick_output_path("ai-research", tmp_path, now)
    assert p == tmp_path / "ai-research" / "2026-05-20-070000.md"
