import time
from datetime import datetime, timezone
from pathlib import Path

from scout.agent.llm import Response, ToolCall
from scout.agent.loop import run_loop
from scout.agent.tools._types import RunContext
from tests.fakes.llm import FakeLLMClient


def ctx_for(tmp_path: Path) -> RunContext:
    return RunContext(
        slug="t", output_dir=tmp_path, logs_dir=tmp_path,
        now=datetime(2026, 5, 20, 7, tzinfo=timezone.utc),
    )


def test_happy_path_writes_digest(tmp_path):
    tool_call = ToolCall(id="1", name="write_digest", arguments={"markdown_body": "# Hi"})
    client = FakeLLMClient([
        Response(text=None, tool_calls=[tool_call]),
    ])
    result = run_loop(
        client=client, model="m",
        system_prompt="sys", user_prompt="usr",
        ctx=ctx_for(tmp_path),
        allowed_tools=["write_digest"], timeout_seconds=30,
    )
    assert result.status == "ok"
    assert (tmp_path / "t" / "2026-05-20.md").exists()


def test_no_digest_fails(tmp_path):
    client = FakeLLMClient([Response(text="all done", tool_calls=[])])
    result = run_loop(
        client=client, model="m",
        system_prompt="sys", user_prompt="usr",
        ctx=ctx_for(tmp_path),
        allowed_tools=["write_digest"], timeout_seconds=30,
    )
    assert result.status == "failed"
    assert result.reason == "no_digest"


def test_timeout(tmp_path):
    class SlowClient:
        def call(self, *a, **kw):
            time.sleep(0.2)
            return Response(text=None, tool_calls=[
                ToolCall(id="1", name="read_history", arguments={})
            ])
    result = run_loop(
        client=SlowClient(), model="m",
        system_prompt="sys", user_prompt="usr",
        ctx=ctx_for(tmp_path),
        allowed_tools=["read_history", "write_digest"], timeout_seconds=0.1,
    )
    assert result.status == "failed"
    assert result.reason == "timeout"
