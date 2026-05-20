from pytest_httpserver import HTTPServer

from scout.agent.tools import web_search as ws

PAYLOAD = {
    "web": {"results": [
        {"title": "T1", "url": "https://x/1", "description": "S1"},
        {"title": "T2", "url": "https://x/2", "description": "S2"},
    ]}
}


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    r = ws.handler(None, query="hello")
    assert r["ok"] is False


def test_basic_search(monkeypatch, httpserver: HTTPServer):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "k")
    monkeypatch.setattr(ws, "ENDPOINT", httpserver.url_for("/search"))
    ws._CACHE.clear()
    httpserver.expect_request("/search").respond_with_json(PAYLOAD)
    r = ws.handler(None, query="hello", num_results=2)
    assert r["ok"] is True
    assert len(r["results"]) == 2
    assert r["results"][0]["title"] == "T1"


def test_cache_returns_same(monkeypatch, httpserver: HTTPServer):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "k")
    monkeypatch.setattr(ws, "ENDPOINT", httpserver.url_for("/search"))
    ws._CACHE.clear()
    httpserver.expect_request("/search").respond_with_json(PAYLOAD)
    r1 = ws.handler(None, query="same")
    r2 = ws.handler(None, query="same")
    assert r1 == r2
