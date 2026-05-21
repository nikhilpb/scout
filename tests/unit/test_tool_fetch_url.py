from pytest_httpserver import HTTPServer

from scout.agent.tools.fetch_url import handler as fetch_handler

HTML = """<html><body><article><h1>Title</h1><p>Body.</p></article></body></html>"""

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>F</title>
  <item><title>A</title><link>https://x/a</link><description>aa</description></item>
  <item><title>B</title><link>https://x/b</link><description>bb</description></item>
</channel></rss>
"""


def test_html(httpserver: HTTPServer):
    httpserver.expect_request("/h").respond_with_data(HTML, content_type="text/html")
    r = fetch_handler(None, url=httpserver.url_for("/h"))
    assert r["ok"] is True
    assert "Body." in r["text"]


def test_rss(httpserver: HTTPServer):
    httpserver.expect_request("/r").respond_with_data(RSS, content_type="application/rss+xml")
    r = fetch_handler(None, url=httpserver.url_for("/r"))
    assert r["ok"] is True
    assert "A" in r["text"] and "B" in r["text"]


def test_http_error_returns_error_field(httpserver: HTTPServer):
    httpserver.expect_request("/e").respond_with_data("nope", status=503)
    r = fetch_handler(None, url=httpserver.url_for("/e"))
    assert r["ok"] is False
    assert "error" in r
