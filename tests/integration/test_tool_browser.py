import pytest
from pytest_httpserver import HTTPServer


@pytest.mark.browser
def test_browser_renders(httpserver: HTTPServer):
    from scout.agent.tools.browser import handler
    html = "<html><body><div id='go'>Hello</div></body></html>"
    httpserver.expect_request("/p").respond_with_data(html, content_type="text/html")
    r = handler(None, url=httpserver.url_for("/p"), wait_for_selector="#go")
    assert r["ok"] is True
    assert "Hello" in r["text"]
