"""fetch_rss_feed — fetches and parses an RSS feed into plain title/url/source dicts."""

from __future__ import annotations

import feedparser
import httpx

from agent_kit.errors import FeedFetchError


def fetch_rss_feed(url: str) -> list[dict[str, str]]:
    try:
        response = httpx.get(url, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise FeedFetchError(
            f"feed '{url}' returned HTTP {e.response.status_code}"
        ) from e
    except httpx.RequestError as e:
        raise FeedFetchError(f"failed to fetch feed '{url}': {e}") from e

    feed = feedparser.parse(response.text)
    source = feed.feed.get("title", url)
    return [
        {"title": entry.get("title", ""), "url": entry.get("link", ""), "source": source}
        for entry in feed.entries
    ]
