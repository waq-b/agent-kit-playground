import agent_kit
from agent_kit.agents.models.news import NewsOutput
from agent_kit.registry import get_registry


def test_news_agent_registered_at_startup(isolated_registries):
    listing = get_registry().list()
    assert any(d["name"] == "news" for d in listing)


def test_stub_returns_news_output_with_at_least_two_valid_items(isolated_registries):
    result = agent_kit.run_agent("news", {"keywords": ["AI"]})
    assert isinstance(result, NewsOutput)
    assert len(result.items) >= 2
    for item in result.items:
        assert item.title
        assert item.source
        assert item.url
        assert item.relevance_note
