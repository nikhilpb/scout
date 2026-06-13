from datetime import datetime, timezone

from scout.trajectory import TrajectoryWriter, new_ulid, provider_of
from tests.conftest import read_trajectory


def test_new_ulid_format_and_time_sortable():
    a = new_ulid(datetime(2026, 6, 13, tzinfo=timezone.utc))
    b = new_ulid(datetime(2026, 6, 14, tzinfo=timezone.utc))
    assert len(a) == 26 and a.isalnum() and a.isupper()
    assert a < b  # a later timestamp sorts lexicographically after


def test_provider_of():
    assert provider_of("anthropic/claude-sonnet-4-6", "builtin") == "anthropic"
    assert provider_of("gemini/gemini-2.5-flash", "builtin") == "gemini"
    assert provider_of(None, "claude-code") == "anthropic"
    assert provider_of(None, "builtin") == "unknown"


def test_writer_emits_schema_valid_records(tmp_path):
    now = datetime(2026, 6, 13, 3, 0, 0, tzinfo=timezone.utc)
    with TrajectoryWriter("ai", tmp_path, now=now) as tw:
        assert tw.path.name == f"{tw.run_id}.jsonl"
        tw.header(topic="ai", title="AI", runner="builtin", model="m", provider="x")
        tw.message("system", "You are scout.")
        tw.message("user", "go")
        a = tw.message(
            "assistant",
            [
                {"type": "text", "text": "ok"},
                {"type": "tool_use", "call_id": "c1", "name": "web_search",
                 "input": {"q": "x"}},
            ],
            model="m", stop_reason="tool_use",
            usage={"input_tokens": 5, "output_tokens": 2, "cost_usd": 0.001},
        )
        tc = tw.tool_call(call_id="c1", name="web_search", arguments={"q": "x"}, parent_id=a)
        tw.tool_result(call_id="c1", status="ok", result={"content": "hits"},
                       parent_id=tc, duration_ms=12)
        tw.note_usage(input_tokens=5, output_tokens=2, cost_usd=0.001)
        tw.artifact(kind="digest", path="output/ai/2026-06-13.md",
                    media_type="text/markdown", size_bytes=10)
        tw.result(status="ok", duration_seconds=1.0)

    recs = read_trajectory(tw.path)  # asserts every record matches the schema
    assert [r["type"] for r in recs] == [
        "run", "message", "message", "message", "tool_call", "tool_result",
        "artifact", "result",
    ]
    # envelope invariants: seq is dense and 0-based; header id == run id
    assert [r["seq"] for r in recs] == list(range(len(recs)))
    assert recs[0]["id"] == tw.run_id and recs[0]["parent_id"] is None
    # tool_result links back to its tool_call
    tr = next(r for r in recs if r["type"] == "tool_result")
    assert tr["parent_id"] == tc
    # aggregates feed both the frontmatter summary and the result record
    assert tw.summary()["tool_calls"] == {"web_search": 1}
    assert tw.summary()["tokens"] == {"input": 5, "output": 2}
    res = recs[-1]
    assert res["usage"]["input_tokens"] == 5
    assert res["tool_calls"] == {"web_search": 1}


def test_partial_trajectory_without_result_is_valid(tmp_path):
    """A crash mid-run leaves a header + partial body — still schema-valid."""
    now = datetime(2026, 6, 13, tzinfo=timezone.utc)
    with TrajectoryWriter("ai", tmp_path, now=now) as tw:
        tw.header(topic="ai", runner="builtin", model="m")
        tw.message("user", "hi")
    recs = read_trajectory(tw.path)
    assert recs[0]["type"] == "run"
    assert recs[-1]["type"] == "message"
