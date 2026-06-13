from datetime import datetime, timezone
from pathlib import Path

import pytest

from scout.agent.llm import Response, ToolCall
from scout.config import LoadedTopic, TopicConfig
from scout.runner import Limits, Paths, make_runner
from scout.trajectory import TrajectoryWriter
from tests.conftest import only_trajectory
from tests.fakes.llm import FakeLLMClient

TOPIC = LoadedTopic(
    slug="ai",
    path=Path("topics/ai.yaml"),
    config=TopicConfig(
        title="AI", description="AI research.",
        cadence="0 7 * * *", model="anthropic/claude-sonnet-4-6",
        prompt={"template": "briefing"},
    ),
)


@pytest.mark.integration
def test_builtin_run_writes_full_digest(tmp_path, monkeypatch):
    from scout.runners import builtin as br
    fake = FakeLLMClient([
        Response(
            text=None,
            tool_calls=[ToolCall(
                id="1", name="write_digest",
                arguments={"markdown_body": "# AI today\n\nBody."},
            )],
            input_tokens=100, output_tokens=10, cost_usd=0.01,
        )
    ])
    monkeypatch.setattr(br, "default_llm_client", lambda: fake)

    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "briefing.md").write_text("Write a briefing on {{title}}.")
    monkeypatch.setattr(br, "PROMPTS_DIR", prompts_dir)

    output_dir = tmp_path / "output"
    traj_dir = tmp_path / "trajectories"
    now = datetime(2026, 5, 20, 7, 0, 0, tzinfo=timezone.utc)
    runner = make_runner("builtin")
    with TrajectoryWriter("ai", traj_dir, now=now) as tw:
        result = runner.execute(
            TOPIC,
            Paths(output_dir=output_dir, trajectories_dir=traj_dir),
            Limits(timeout_seconds=10),
            traj=tw, now=now,
        )
    assert result.status == "ok"
    p = output_dir / "ai" / "2026-05-20.md"
    assert p.exists()
    content = p.read_text()
    assert content.startswith("---\n")
    assert "topic: ai" in content
    assert "# AI today" in content
    # telemetry is captured in the digest frontmatter
    assert "write_digest: 1" in content
    assert "input: 100" in content
    assert "output: 10" in content
    assert "cost_usd: 0.01" in content
    # one schema-valid trajectory with messages, the tool call/result, artifact, result
    recs = only_trajectory(traj_dir, "ai")
    types = [r["type"] for r in recs]
    assert "message" in types
    assert "tool_call" in types
    assert "tool_result" in types
    assert "artifact" in types
    assert types[-1] == "result"
    assert recs[-1]["status"] == "ok"
    assert recs[-1]["tool_calls"] == {"write_digest": 1}
    tool_names = [r["name"] for r in recs if r["type"] == "tool_call"]
    assert tool_names == ["write_digest"]
    # the assistant turn records its model and token usage
    assistant = next(
        r for r in recs if r["type"] == "message" and r["role"] == "assistant"
    )
    assert assistant["usage"]["input_tokens"] == 100
    assert assistant["usage"]["output_tokens"] == 10
    # the digest is recorded as an artifact pointing at the output file
    artifact = next(r for r in recs if r["type"] == "artifact")
    assert artifact["path"] == "output/ai/2026-05-20.md"
    assert artifact["kind"] == "digest"
