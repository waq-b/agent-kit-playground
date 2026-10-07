import pytest
from fastapi.testclient import TestClient

import agent_kit.builder as builder_module
import agent_kit.card_store as card_store_module
import agent_kit.gm as gm_module
from agent_kit.builder import BuilderPaths
from agent_kit.errors import GMUnavailableError
from agent_kit.gm import GMSynthesis
from agent_kit.playground.app import app
from agent_kit.registry import get_registry


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(builder_module, "DEFAULT_PATHS", BuilderPaths(data_dir=tmp_path / "agent_kit_data"))
    store = card_store_module.CardStore(":memory:")
    monkeypatch.setattr(card_store_module, "_card_store", store)
    yield store


def _seed_hello(store):
    """Seed hello's card state so the queue/suggestion endpoints have something real."""
    definition = get_registry().get("hello")
    store.ensure_seeded("hello", definition.card)
    return definition


def test_queue_is_empty_initially(client, isolated_registries, _isolated_stores):
    r = client.get("/api/v1/gm/queue")
    assert r.status_code == 200
    assert r.json() == []


def test_queue_lists_debuffed_agents(client, isolated_registries, _isolated_stores):
    _seed_hello(_isolated_stores)
    _isolated_stores.store_traits("hello", "warmth=warm", "A paragraph.")
    _isolated_stores.mark_traits_stale("hello")

    r = client.get("/api/v1/gm/queue")
    assert r.status_code == 200
    entries = r.json()
    assert [e["agent_name"] for e in entries] == ["hello"]
    assert entries[0]["pending_since"] is not None


def test_roster_shows_awaiting_respec_badge_flag(client, isolated_registries, _isolated_stores):
    _seed_hello(_isolated_stores)
    _isolated_stores.store_traits("hello", "sig", "p")
    _isolated_stores.mark_traits_stale("hello")

    cards = client.get("/api/v1/cards").json()
    hello_card = next(c for c in cards if c["name"] == "hello")
    assert hello_card["awaiting_respec"] is True


def test_process_queue_resynthesizes_and_clears_debuff(client, isolated_registries, _isolated_stores, monkeypatch):
    _seed_hello(_isolated_stores)
    _isolated_stores.store_traits("hello", "old-sig", "Old paragraph.")
    _isolated_stores.mark_traits_stale("hello")

    monkeypatch.setattr(
        gm_module, "synthesize_traits",
        lambda *a, **k: GMSynthesis(trait_paragraph="Freshly respecced."),
    )

    r = client.post("/api/v1/gm/queue/process")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["processed"] == 1
    assert data["resynthesized"] == ["hello"]
    assert data["still_pending"] == []

    assert client.get("/api/v1/gm/queue").json() == []
    assert _isolated_stores.get_traits("hello").trait_paragraph == "Freshly respecced."


def test_process_queue_keeps_agents_pending_when_gm_still_down(
    client, isolated_registries, _isolated_stores, monkeypatch
):
    _seed_hello(_isolated_stores)
    _isolated_stores.store_traits("hello", "sig", "Old paragraph.")
    _isolated_stores.mark_traits_stale("hello")

    def _still_down(*args, **kwargs):
        raise GMUnavailableError("GM still down")

    monkeypatch.setattr(gm_module, "synthesize_traits", _still_down)

    data = client.post("/api/v1/gm/queue/process").json()
    assert data["resynthesized"] == []
    assert data["still_pending"] == ["hello"]
    # stays queued for the next attempt, and keeps serving the old paragraph
    assert [e["agent_name"] for e in client.get("/api/v1/gm/queue").json()] == ["hello"]
    assert _isolated_stores.get_traits("hello").trait_paragraph == "Old paragraph."


def test_process_queue_records_suggestions(client, isolated_registries, _isolated_stores, monkeypatch):
    _seed_hello(_isolated_stores)
    _isolated_stores.store_traits("hello", "sig", "p")
    _isolated_stores.mark_traits_stale("hello")

    monkeypatch.setattr(
        gm_module, "synthesize_traits",
        lambda *a, **k: GMSynthesis(
            trait_paragraph="p2", conflicts=["a clash"], suggested_system_prompt="better prompt"
        ),
    )
    client.post("/api/v1/gm/queue/process")

    suggestions = client.get("/api/v1/gm/suggestions").json()
    assert len(suggestions) == 1
    assert suggestions[0]["suggested_system_prompt"] == "better prompt"
    assert suggestions[0]["rationale"] == "a clash"


def test_approve_suggestion_applies_the_prompt(client, isolated_registries, _isolated_stores):
    definition = _seed_hello(_isolated_stores)
    original_prompt = definition.system_prompt
    suggestion = _isolated_stores.record_suggestion(
        "hello", original_prompt, "A GM-improved greeting prompt.", "why"
    )

    r = client.post(f"/api/v1/gm/suggestions/{suggestion.id}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"

    # applied through the normal builder path, so the live registry reflects it
    assert get_registry().get("hello").system_prompt == "A GM-improved greeting prompt."
    assert client.get("/api/v1/gm/suggestions").json() == []


def test_reject_suggestion_leaves_the_prompt_unchanged(client, isolated_registries, _isolated_stores):
    definition = _seed_hello(_isolated_stores)
    original_prompt = definition.system_prompt
    suggestion = _isolated_stores.record_suggestion(
        "hello", original_prompt, "An unwanted rewrite.", "why"
    )

    r = client.post(f"/api/v1/gm/suggestions/{suggestion.id}/reject")
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert get_registry().get("hello").system_prompt == original_prompt
    assert client.get("/api/v1/gm/suggestions").json() == []


def test_unknown_suggestion_id_returns_404(client, isolated_registries, _isolated_stores):
    assert client.post("/api/v1/gm/suggestions/9999/approve").status_code == 404
    assert client.post("/api/v1/gm/suggestions/9999/reject").status_code == 404


def test_suggestions_status_filter(client, isolated_registries, _isolated_stores):
    suggestion = _isolated_stores.record_suggestion("hello", "old", "new", "why")
    client.post(f"/api/v1/gm/suggestions/{suggestion.id}/reject")

    assert client.get("/api/v1/gm/suggestions").json() == []
    assert len(client.get("/api/v1/gm/suggestions", params={"status": "all"}).json()) == 1
    assert len(client.get("/api/v1/gm/suggestions", params={"status": "rejected"}).json()) == 1
