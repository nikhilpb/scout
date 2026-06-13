from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from scout.server import trajectories as tj
from scout.server.trajectory_app import create_trajectory_app
from scout.trajectory import TrajectoryWriter
from tests.conftest import make_data_paths


def write_trajectory(data, slug="ai-news", title="AI News", status="ok"):
    now = datetime(2026, 6, 13, 3, 0, 0, tzinfo=timezone.utc)
    with TrajectoryWriter(slug, data.trajectories_dir, now=now) as tw:
        tw.header(topic=slug, title=title, runner="claude-code", model="claude-opus-4-8",
                  provider="anthropic", config={"sources": [{"type": "web", "url": "https://x"}]})
        tw.message("user", "Produce the digest.")
        a = tw.message(
            "assistant",
            [{"type": "reasoning", "text": "thinking about it"},
             {"type": "tool_use", "call_id": "c1", "name": "WebFetch", "input": {"url": "https://x"}}],
            model="claude-opus-4-8",
        )
        tc = tw.tool_call(call_id="c1", name="WebFetch", arguments={"url": "https://x"},
                          parent_id=a)
        tw.tool_result(call_id="c1", status="ok", result={"bytes": 100}, parent_id=tc,
                       sources=[{"url": "https://x", "title": "Source X"}])
        tw.note_usage(input_tokens=1000, output_tokens=50, cost_usd=0.12)
        tw.artifact(kind="digest", path=f"output/{slug}/2026-06-13.md",
                    media_type="text/markdown", summary="AI News")
        tw.result(status=status, duration_seconds=12.5, num_turns=3,
                  usage={"input_tokens": 1000, "output_tokens": 50, "cost_usd": 0.12})
    return tw.run_id


@pytest.fixture
def env(tmp_path):
    data = make_data_paths(tmp_path)
    run_id = write_trajectory(data)
    return data, run_id, TestClient(create_trajectory_app(data))


def test_reader_lists_runs(env):
    data, run_id, _ = env
    runs = tj.list_runs(data, "ai-news")
    assert len(runs) == 1
    r = runs[0]
    assert r.run_id == run_id
    assert r.status == "ok"
    assert r.cost_usd == 0.12
    assert r.num_turns == 3
    assert r.tool_calls == {"WebFetch": 1}
    assert r.title == "AI News"


def test_reader_load_trajectory(env):
    data, run_id, _ = env
    doc = tj.load_trajectory(data, "ai-news", run_id)
    assert doc is not None
    assert doc.header["type"] == "run"
    assert doc.result["status"] == "ok"
    assert [r["type"] for r in doc.records][0] == "run"


def test_index_page(env):
    _, run_id, client = env
    res = client.get("/")
    assert res.status_code == 200
    assert "AI News" in res.text
    assert f"/r/ai-news/{run_id}" in res.text


def test_topic_page(env):
    _, _, client = env
    assert client.get("/t/ai-news").status_code == 200
    assert client.get("/t/nope").status_code == 404


def test_detail_page_renders_records(env):
    _, run_id, client = env
    res = client.get(f"/r/ai-news/{run_id}")
    assert res.status_code == 200
    text = res.text
    assert "WebFetch" in text                       # tool call
    assert "thinking about it" in text              # reasoning part
    assert "claude-opus-4-8" in text                # model
    assert "output/ai-news/2026-06-13.md" in text   # artifact path
    assert "Source X" in text                       # source link


def test_detail_404_and_no_traversal(env):
    _, _, client = env
    assert client.get("/r/ai-news/NOTAREALRUN").status_code == 404
    assert client.get("/r/ai-news/..%2f..%2fsecret").status_code == 404


def test_api_json(env):
    _, run_id, client = env
    res = client.get(f"/api/r/ai-news/{run_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["summary"]["status"] == "ok"
    assert any(rec["type"] == "result" for rec in body["records"])


def test_healthz(env):
    _, _, client = env
    assert client.get("/healthz").json() == {"ok": True}
