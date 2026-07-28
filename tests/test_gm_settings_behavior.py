"""The three settings-driven GM behaviours added in v0.5.

Respec threshold, auto-process, and the suggestions kill-switch — each is a real
behaviour change in the service, not just a stored value, so each gets tested
through the endpoints that trigger it.
"""

import os

import pytest
from fastapi.testclient import TestClient

import agent_kit.builder as builder_module
import agent_kit.card_store as card_store_module
import agent_kit.gm as gm_module
import agent_kit.playground.app as app_module
from agent_kit.builder import BuilderPaths
from agent_kit.gm import GMSynthesis
from agent_kit.playground.app import app
from agent_kit.registry import get_registry
from agent_kit.settings import PlaygroundSettings, save_settings


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_KIT_DATA_DIR", str(tmp_path / "agent_kit_data"))
    monkeypatch.setattr(
        builder_module, "DEFAULT_PATHS", BuilderPaths(data_dir=tmp_path / "agent_kit_data")
    )
    store = card_store_module.CardStore(":memory:")
    monkeypatch.setattr(card_store_module, "_card_store", store)
    saved = dict(os.environ)
    yield store
    os.environ.clear()
    os.environ.update(saved)


def _seed_hello_with_traits(store):
    definition = get_registry().get("hello")
    store.ensure_seeded("hello", definition.card)
    store.store_traits("hello", "warmth=warm", "A synthesized paragraph.")
    return definition


def _grade(client, times=1):
    last = None
    for _ in range(times):
        last = client.post("/api/v1/agents/hello/grade", json={"action": "thumbs_up"})
        assert last.status_code == 200
    return last.json()


# --- respec threshold ---


def test_event_count_resets_when_traits_are_resynthesized(isolated_registries, _isolated):
    store = _isolated
    _seed_hello_with_traits(store)
    store.record_xp_event("hello", "thumbs_up")
    store.record_xp_event("hello", "thumbs_up")
    assert store.count_events_since_synthesis("hello") == 2

    store.store_traits("hello", "warmth=warm", "A fresher paragraph.")
    assert store.count_events_since_synthesis("hello") == 0


def test_agent_with_no_traits_row_never_trips_the_threshold(isolated_registries, _isolated):
    store = _isolated
    definition = get_registry().get("hello")
    store.ensure_seeded("hello", definition.card)
    store.record_xp_event("hello", "thumbs_up")
    assert store.count_events_since_synthesis("hello") == 0


def test_grading_below_threshold_does_not_queue_a_respec(client, isolated_registries, _isolated):
    _seed_hello_with_traits(_isolated)
    save_settings(PlaygroundSettings(respec_threshold=3))

    body = _grade(client, times=2)
    assert body["events_since_respec"] == 2
    assert body["respec_queued"] is False
    assert client.get("/api/v1/gm/queue").json() == []


def test_reaching_the_threshold_queues_a_respec(client, isolated_registries, _isolated):
    _seed_hello_with_traits(_isolated)
    save_settings(PlaygroundSettings(respec_threshold=3))

    body = _grade(client, times=3)
    assert body["events_since_respec"] == 3
    assert body["respec_queued"] is True
    assert [e["agent_name"] for e in client.get("/api/v1/gm/queue").json()] == ["hello"]


def test_respec_queued_is_reported_once_not_on_every_later_grade(
    client, isolated_registries, _isolated
):
    """Already-stale agents stay queued; they don't re-queue on each grade."""
    _seed_hello_with_traits(_isolated)
    save_settings(PlaygroundSettings(respec_threshold=2))

    assert _grade(client, times=2)["respec_queued"] is True
    assert _grade(client, times=1)["respec_queued"] is False


def test_threshold_is_read_from_settings_not_hardcoded(client, isolated_registries, _isolated):
    _seed_hello_with_traits(_isolated)
    save_settings(PlaygroundSettings(respec_threshold=1))
    assert _grade(client, times=1)["respec_queued"] is True


# --- auto-process ---


def test_auto_process_off_leaves_the_agent_in_the_queue(client, isolated_registries, _isolated):
    _seed_hello_with_traits(_isolated)
    save_settings(PlaygroundSettings(respec_threshold=1, auto_process_respec=False))

    body = _grade(client, times=1)
    assert body["respec_queued"] is True
    assert body["respec_processed"] is False
    assert len(client.get("/api/v1/gm/queue").json()) == 1


def test_auto_process_on_resynthesizes_within_the_grade_request(
    client, isolated_registries, _isolated, monkeypatch
):
    _seed_hello_with_traits(_isolated)
    save_settings(PlaygroundSettings(respec_threshold=1, auto_process_respec=True))
    monkeypatch.setattr(
        gm_module,
        "synthesize_traits",
        lambda *a, **k: GMSynthesis(
            trait_paragraph="Freshly synthesized.", suggested_system_prompt="", conflicts=[]
        ),
    )

    body = _grade(client, times=1)
    assert body["respec_queued"] is True
    assert body["respec_processed"] is True
    # Queue drained synchronously — no waiting on a background worker.
    assert client.get("/api/v1/gm/queue").json() == []
    assert _isolated.get_traits("hello").trait_paragraph == "Freshly synthesized."


def test_auto_process_leaves_the_agent_queued_when_the_gm_is_unavailable(
    client, isolated_registries, _isolated, monkeypatch
):
    from agent_kit.errors import GMUnavailableError

    _seed_hello_with_traits(_isolated)
    save_settings(PlaygroundSettings(respec_threshold=1, auto_process_respec=True))

    def _boom(*a, **k):
        raise GMUnavailableError("the GM is down")

    monkeypatch.setattr(gm_module, "synthesize_traits", _boom)

    body = _grade(client, times=1)
    assert body["respec_processed"] is False
    assert [e["agent_name"] for e in client.get("/api/v1/gm/queue").json()] == ["hello"]


# --- suggestions kill-switch ---


def test_queue_process_records_a_suggestion_when_enabled(
    client, isolated_registries, _isolated, monkeypatch
):
    store = _isolated
    _seed_hello_with_traits(store)
    store.mark_traits_stale("hello")
    save_settings(PlaygroundSettings(suggestions_enabled=True))
    monkeypatch.setattr(
        gm_module,
        "synthesize_traits",
        lambda *a, **k: GMSynthesis(
            trait_paragraph="p", suggested_system_prompt="a better prompt", conflicts=["c"]
        ),
    )

    client.post("/api/v1/gm/queue/process")
    assert len(client.get("/api/v1/gm/suggestions").json()) == 1


def test_queue_process_records_no_suggestion_when_disabled(
    client, isolated_registries, _isolated, monkeypatch
):
    store = _isolated
    _seed_hello_with_traits(store)
    store.mark_traits_stale("hello")
    save_settings(PlaygroundSettings(suggestions_enabled=False))
    monkeypatch.setattr(
        gm_module,
        "synthesize_traits",
        lambda *a, **k: GMSynthesis(
            trait_paragraph="p", suggested_system_prompt="a better prompt", conflicts=["c"]
        ),
    )

    r = client.post("/api/v1/gm/queue/process")
    # The respec itself still happens — only the prompt suggestion is suppressed.
    assert r.json()["resynthesized"] == ["hello"]
    assert client.get("/api/v1/gm/suggestions").json() == []
    assert store.get_traits("hello").trait_paragraph == "p"


def test_runner_records_no_suggestion_when_disabled(
    isolated_registries, _isolated, monkeypatch
):
    """The runner's own synthesis path honours the same switch."""
    from agent_kit.runner import Runner
    from agent_kit.stat_effects import resolve_effects

    store = _isolated
    definition = get_registry().get("hello")
    store.ensure_seeded("hello", definition.card)
    save_settings(PlaygroundSettings(suggestions_enabled=False, stub_mode=False))
    monkeypatch.setattr(
        gm_module,
        "synthesize_traits",
        lambda *a, **k: GMSynthesis(
            trait_paragraph="p", suggested_system_prompt="a better prompt", conflicts=[]
        ),
    )

    stat_defs = {
        **definition.card.main_class.stats,
        **(definition.card.sub_class.stats if definition.card.sub_class else {}),
    }
    resolved = resolve_effects(stat_defs, store.get_state("hello").class_stats)
    Runner()._resolve_trait_paragraph(definition, resolved, store)

    assert store.list_suggestions() == []
