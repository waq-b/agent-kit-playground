from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

import agent_kit.card_store as card_store_module
from agent_kit.definition import AgentDefinition
from agent_kit.playground.app import app
from agent_kit.registry import get_registry


class _NoCardOut(BaseModel):
    x: str


def _register_card_less_agent() -> None:
    get_registry().register(
        AgentDefinition(
            name="no_card_agent", description="d", system_prompt="sp", model="m",
            temperature=0.7, tools=[], output_model=_NoCardOut, source_path=Path("x.yaml"),
        )
    )


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_card_store(monkeypatch):
    fresh_store = card_store_module.CardStore(":memory:")
    monkeypatch.setattr(card_store_module, "_card_store", fresh_store)
    yield fresh_store


def test_list_cards_returns_only_carded_agents(client, isolated_registries):
    r = client.get("/api/v1/cards")
    assert r.status_code == 200
    names = {c["name"] for c in r.json()}
    assert names == {"hello", "news", "webpage"}  # all built-in agents have cards


def test_list_cards_returns_correct_summary_fields(client, isolated_registries):
    r = client.get("/api/v1/cards")
    hello_card = next(c for c in r.json() if c["name"] == "hello")
    assert hello_card["title"] == "Greeter"
    assert hello_card["main_class"] == "greeter"
    assert hello_card["sub_class"] is None
    assert hello_card["level"] == 1
    assert hello_card["xp"] == 0
    assert "warmth" in hello_card["class_stats"]

    news_card = next(c for c in r.json() if c["name"] == "news")
    assert news_card["title"] == "News Hound Investigator"
    assert news_card["sub_class"] == "investigator"


def test_get_card_detail_includes_backstory_and_unlock_table(client, isolated_registries):
    r = client.get("/api/v1/agents/news/card")
    assert r.status_code == 200
    data = r.json()
    assert data["backstory"]
    assert len(data["unlock_table"]) == 3
    assert data["tool_proficiency"] == {}


def test_get_card_for_unknown_agent_returns_404(client, isolated_registries):
    r = client.get("/api/v1/agents/does-not-exist/card")
    assert r.status_code == 404


def test_grade_unknown_agent_returns_404(client, isolated_registries):
    r = client.post("/api/v1/agents/does-not-exist/grade", json={"action": "thumbs_up"})
    assert r.status_code == 404


def test_grade_unknown_action_returns_422(client, isolated_registries):
    r = client.post("/api/v1/agents/hello/grade", json={"action": "not_a_real_action"})
    assert r.status_code == 422


def test_grade_updates_xp_and_reflects_in_card_list(client, isolated_registries):
    r = client.post("/api/v1/agents/hello/grade", json={"action": "thumbs_up"})
    assert r.status_code == 200
    data = r.json()
    assert data["xp_delta"] == 10
    assert data["new_xp"] == 10
    assert data["leveled_up"] is False

    r2 = client.get("/api/v1/cards")
    hello_card = next(c for c in r2.json() if c["name"] == "hello")
    assert hello_card["xp"] == 10


def test_grade_with_tool_used_tracks_proficiency(client, isolated_registries):
    client.post("/api/v1/agents/news/grade", json={"action": "thumbs_up", "tool_used": "fetch_rss_feed"})
    r = client.get("/api/v1/agents/news/card")
    assert r.json()["tool_proficiency"]["fetch_rss_feed"]["xp"] == 10


def test_get_card_for_agent_without_card_returns_404(client, isolated_registries):
    _register_card_less_agent()
    r = client.get("/api/v1/agents/no_card_agent/card")
    assert r.status_code == 404


def test_grade_agent_without_card_returns_400(client, isolated_registries):
    _register_card_less_agent()
    r = client.post("/api/v1/agents/no_card_agent/grade", json={"action": "thumbs_up"})
    assert r.status_code == 400
