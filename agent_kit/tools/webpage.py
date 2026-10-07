"""fetch_page_text — fetches a web page and returns its visible text, truncated."""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from agent_kit.errors import PageFetchError

MAX_CHARS = 8000
_SKIPPED_TAGS = {"script", "style", "noscript", "template", "svg", "head"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "title":
            self._in_title = True
        elif tag in _SKIPPED_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in _SKIPPED_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip_depth and data.strip():
            self._chunks.append(data.strip())

    @property
    def text(self) -> str:
        return " ".join(self._chunks)


def fetch_page_text(url: str) -> dict[str, str]:
    """Return {"url", "title", "text"} for an http(s) page; text is capped at MAX_CHARS."""
    if urlparse(url).scheme not in ("http", "https"):
        raise PageFetchError(f"only http(s) URLs can be fetched, got '{url}'")
    try:
        response = httpx.get(url, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise PageFetchError(f"page '{url}' returned HTTP {e.response.status_code}") from e
    except httpx.RequestError as e:
        raise PageFetchError(f"failed to fetch page '{url}': {e}") from e

    parser = _TextExtractor()
    parser.feed(response.text)
    return {"url": url, "title": parser.title.strip(), "text": parser.text[:MAX_CHARS]}
