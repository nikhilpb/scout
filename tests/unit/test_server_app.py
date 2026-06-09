import pytest
from fastapi.testclient import TestClient

from scout.feedback import parse_blocks
from scout.server.app import create_app
from tests.unit.test_server_digests import make_data, write_digest


@pytest.fixture
def env(tmp_path):
    data = make_data(tmp_path)
    write_digest(data, "ai-news", "2026-06-08")
    (data.topics_dir / "ai-news.yaml").write_text("title: AI News\ndescription: Daily AI.\n")
    return data, TestClient(create_app(data))


def test_home_lists_latest(env):
    _, client = env
    res = client.get("/")
    assert res.status_code == 200
    assert "/t/ai-news/2026-06-08" in res.text
    assert "AI News" in res.text


def test_topics_page(env):
    _, client = env
    res = client.get("/topics")
    assert res.status_code == 200
    assert "/t/ai-news" in res.text
    assert "Daily AI." in res.text
    assert "digest-index" in res.text


def test_topic_page(env):
    _, client = env
    res = client.get("/t/ai-news")
    assert res.status_code == 200
    assert "/t/ai-news/2026-06-08" in res.text


def test_topic_page_unknown_404(env):
    _, client = env
    assert client.get("/t/nope").status_code == 404


def test_digest_page_renders(env):
    _, client = env
    res = client.get("/t/ai-news/2026-06-08")
    assert res.status_code == 200
    assert "<h1>AI News — June 8, 2026</h1>" in res.text
    assert "scout-feedback" not in res.text
    assert "Run details" in res.text
    assert "gemini/gemini-3.5-flash" in res.text
    # Existing feedback block is surfaced in the feedback section.
    assert "solid digest" in res.text


def test_digest_page_traversal_404(env):
    _, client = env
    assert client.get("/t/ai-news/..%2Fsecret").status_code == 404
    assert client.get("/t/ai-news/no-such").status_code == 404


def test_feedback_post_appends_block(env):
    data, client = env
    res = client.post(
        "/api/feedback",
        json={"topic": "ai-news", "name": "2026-06-08", "rating": 5, "notes": "great"},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True
    blocks, errors = parse_blocks((data.output_dir / "ai-news" / "2026-06-08.md").read_text())
    assert errors == 0
    added = blocks[-1]
    assert added["rating"] == 5
    assert added["notes"] == "great"
    assert added["source"] == "web"
    assert "at" in added


def test_feedback_requires_rating_or_notes(env):
    _, client = env
    res = client.post("/api/feedback", json={"topic": "ai-news", "name": "2026-06-08"})
    assert res.status_code == 422
    res = client.post(
        "/api/feedback", json={"topic": "ai-news", "name": "2026-06-08", "rating": 9}
    )
    assert res.status_code == 422


def test_feedback_unknown_digest_404(env):
    _, client = env
    res = client.post(
        "/api/feedback", json={"topic": "ai-news", "name": "../x", "rating": 3}
    )
    assert res.status_code == 404


def test_pwa_assets(env):
    _, client = env
    res = client.get("/manifest.webmanifest")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/manifest+json")
    assert res.json()["display"] == "standalone"
    res = client.get("/sw.js")
    assert res.status_code == 200
    assert "text/javascript" in res.headers["content-type"]
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/favicon.svg").status_code == 200
