import json
from datetime import datetime, timezone

from scout.runlog import RunLog


def test_writes_events(tmp_path):
    with RunLog("ai", tmp_path, now=datetime(2026, 5, 20, 7, 0, 0, tzinfo=timezone.utc)) as rl:
        rl.event("run_start", model="m")
        rl.event("tool_call", tool="web_search", duration_ms=300, result_bytes=100)
        rl.event("llm_turn", turn=1, input_tokens=10, output_tokens=5, cost_usd=0.001)
    files = list((tmp_path / "ai").glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text().splitlines()
    assert len(lines) == 3
    d0 = json.loads(lines[0])
    assert d0["event"] == "run_start" and "ts" in d0


def test_summary_rolls_up(tmp_path):
    with RunLog("ai", tmp_path) as rl:
        rl.event("tool_call", tool="web_search", duration_ms=0, result_bytes=0)
        rl.event("tool_call", tool="web_search", duration_ms=0, result_bytes=0)
        rl.event("tool_call", tool="fetch_url", duration_ms=0, result_bytes=0)
        rl.event("llm_turn", turn=1, input_tokens=10, output_tokens=2, cost_usd=0.01)
        rl.event("llm_turn", turn=2, input_tokens=5, output_tokens=1, cost_usd=0.005)
        s = rl.summary()
    assert s["tool_calls"] == {"web_search": 2, "fetch_url": 1}
    assert s["tokens"] == {"input": 15, "output": 3}
    assert abs(s["cost_usd"] - 0.015) < 1e-9
