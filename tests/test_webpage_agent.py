import httpx
import pytest
from pydantic import ValidationError

import agent_kit
from agent_kit.agents.models.webpage import WebpageOutput
from agent_kit.errors import PageFetchError
from agent_kit.registry import get_registry
from agent_kit.tool_registry import get_tool_registry
from agent_kit.tools import webpage as webpage_tool

HTML = """<html><head><title> Hi </title><style>p {color: red}</style></head>
<body><script>var x = 1;</script><h1>Heading</h1><p>Some <b>bold</b> text.</p></body></html>"""


def test_webpage_agent_registered_with_its_tool(isolated_registries):
    assert any(d["name"] == "webpage" for d in get_registry().list())
    assert "fetch_page_text" in get_tool_registry().list_names()


def test_stub_returns_webpage_output(isolated_registries):
    result = agent_kit.run_agent("webpage", {"url": "https://example.com"})
    assert isinstance(result, WebpageOutput)
    assert result.summary


def test_non_http_url_is_rejected(isolated_registries):
    with pytest.raises(ValidationError):
        agent_kit.run_agent("webpage", {"url": "file:///etc/passwd"})


def test_tool_extracts_visible_text_only(monkeypatch):
    monkeypatch.setattr(
        webpage_tool.httpx, "get",
        lambda url, **kw: httpx.Response(200, text=HTML, request=httpx.Request("GET", url)),
    )
    page = webpage_tool.fetch_page_text("https://example.com/a")
    assert page["title"] == "Hi"
    assert page["text"] == "Heading Some bold text."


def test_tool_truncates_long_pages(monkeypatch):
    body = "<p>" + "word " * 5000 + "</p>"
    monkeypatch.setattr(
        webpage_tool.httpx, "get",
        lambda url, **kw: httpx.Response(200, text=body, request=httpx.Request("GET", url)),
    )
    assert len(webpage_tool.fetch_page_text("https://example.com")["text"]) == webpage_tool.MAX_CHARS


def test_tool_rejects_non_http_scheme():
    with pytest.raises(PageFetchError):
        webpage_tool.fetch_page_text("ftp://example.com/x")


def test_tool_wraps_http_errors(monkeypatch):
    monkeypatch.setattr(
        webpage_tool.httpx, "get",
        lambda url, **kw: httpx.Response(404, request=httpx.Request("GET", url)),
    )
    with pytest.raises(PageFetchError, match="404"):
        webpage_tool.fetch_page_text("https://example.com/missing")
