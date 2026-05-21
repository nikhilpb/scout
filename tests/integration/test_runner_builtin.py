import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scout.agent.llm import Response, ToolCall
from scout.config import LoadedTopic, TopicConfig
from scout.runlog import RunLog
from scout.runner import Limits, Paths, make_runner
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
    logs_dir = tmp_path / "logs"
    now = datetime(2026, 5, 20, 7, 0, 0, tzinfo=timezone.utc)
    runner = make_runner("builtin")
    with RunLog("ai", logs_dir, now=now) as rl:
        result = runner.execute(
            TOPIC,
            Paths(output_dir=output_dir, logs_dir=logs_dir),
            Limits(timeout_seconds=10),
            run_log=rl, now=now,
        )
    assert result.status == "ok"
    p = output_dir / "ai" / "2026-05-20.md"
    assert p.exists()
    content = p.read_text()
    assert content.startswith("---\n")
    assert "topic: ai" in content
    assert "# AI today" in content
    # telemetry is captured
    assert "write_digest: 1" in content
    assert "input: 100" in content
    assert "output: 10" in content
    assert "cost_usd: 0.01" in content
    # per-run JSONL exists and includes llm_turn + tool_call events
    jsonl_files = list((logs_dir / "ai").glob("*.jsonl"))
    assert len(jsonl_files) == 1
    events = [json.loads(line) for line in jsonl_files[0].read_text().splitlines()]
    event_names = [e["event"] for e in events]
    assert "run_start" in event_names
    assert "llm_turn" in event_names
    assert "tool_call" in event_names
    assert "run_end" in event_names
