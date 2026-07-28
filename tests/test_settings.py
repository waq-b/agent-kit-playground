"""Settings persistence, environment application, and the /api/v1/settings endpoints."""

import json
import os

import pytest
from fastapi.testclient import TestClient

import agent_kit.builder as builder_module
import agent_kit.card_store as card_store_module
from agent_kit.builder import BuilderPaths
from agent_kit.playground.app import app
from agent_kit.settings import (
    PlaygroundSettings,
    apply_to_environment,
    load_settings,
    save_settings,
    settings_path,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    """Point the data dir at a tmp dir and restore the environment afterwards.

    `apply_to_environment` deliberately mutates os.environ (that is how the
    call-time readers in runner/gm/notify pick changes up), so every test here
    has to put it back — including the session-wide STUB_AI_PROVIDERS=1 that
    conftest sets for the whole suite.
    """
    monkeypatch.setenv("AGENT_KIT_DATA_DIR", str(tmp_path / "agent_kit_data"))
    monkeypatch.setattr(
        builder_module, "DEFAULT_PATHS", BuilderPaths(data_dir=tmp_path / "agent_kit_data")
    )
    store = card_store_module.CardStore(":memory:")
    monkeypatch.setattr(card_store_module, "_card_store", store)
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


# --- module-level behaviour ---


def test_defaults_when_no_file_exists():
    settings = load_settings()
    assert settings.provider_url == "http://localhost:11434/v1"
    assert settings.respec_threshold == 12
    assert settings.suggestions_enabled is True


def test_seeds_from_environment_when_no_file_exists(monkeypatch):
    monkeypatch.setenv("AGENT_KIT_GM_MODEL", "llama3.1:8b")
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example.com/topic")
    monkeypatch.setenv("STUB_AI_PROVIDERS", "1")

    settings = load_settings()
    assert settings.gm_model == "llama3.1:8b"
    assert settings.ntfy_url == "https://ntfy.example.com/topic"
    assert settings.stub_mode is True


def test_saved_file_wins_over_environment(monkeypatch):
    monkeypatch.setenv("AGENT_KIT_GM_MODEL", "from-env")
    save_settings(PlaygroundSettings(gm_model="from-file"))
    assert load_settings().gm_model == "from-file"


def test_save_round_trips_through_disk():
    save_settings(PlaygroundSettings(respec_threshold=3, auto_process_respec=True))
    assert settings_path().exists()
    assert load_settings().respec_threshold == 3
    assert load_settings().auto_process_respec is True


def test_corrupt_file_falls_back_to_defaults_without_raising():
    settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings_path().write_text("{not json at all")
    assert load_settings().respec_threshold == 12


def test_file_failing_validation_falls_back_to_defaults():
    settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings_path().write_text(json.dumps({"respec_threshold": 9999}))
    assert load_settings().respec_threshold == 12


def test_apply_to_environment_sets_the_call_time_variables():
    apply_to_environment(
        PlaygroundSettings(
            provider_url="http://elsewhere:1234/v1", gm_model="mistral:7b", stub_mode=True
        )
    )
    assert os.environ["AGENT_KIT_PROVIDER_URL"] == "http://elsewhere:1234/v1"
    assert os.environ["AGENT_KIT_GM_MODEL"] == "mistral:7b"
    assert os.environ["STUB_AI_PROVIDERS"] == "1"


def test_stub_mode_off_writes_a_non_one_value():
    apply_to_environment(PlaygroundSettings(stub_mode=False))
    assert os.environ["STUB_AI_PROVIDERS"] != "1"


def test_empty_ntfy_url_unsets_the_variable_entirely():
    os.environ["NTFY_URL"] = "https://stale.example.com"
    apply_to_environment(PlaygroundSettings(ntfy_url=""))
    assert "NTFY_URL" not in os.environ


def test_provider_url_is_read_at_call_time_by_the_runner():
    from agent_kit.runner import provider_base_url

    apply_to_environment(PlaygroundSettings(provider_url="http://swapped:9999/v1"))
    assert provider_base_url() == "http://swapped:9999/v1"


def test_changing_db_path_resets_the_card_store_singleton(monkeypatch, tmp_path):
    """The db path is bound at construction, so it needs an explicit reset."""
    reset_calls = []
    monkeypatch.setattr(
        card_store_module, "reset_card_store", lambda: reset_calls.append(True)
    )
    apply_to_environment(PlaygroundSettings(db_path=str(tmp_path / "other.db")))
    assert reset_calls == [True]


def test_unchanged_db_path_does_not_reset_the_card_store(monkeypatch):
    reset_calls = []
    monkeypatch.setattr(
        card_store_module, "reset_card_store", lambda: reset_calls.append(True)
    )
    os.environ["AGENT_KIT_DB_PATH"] = "agent_kit.db"
    apply_to_environment(PlaygroundSettings(db_path="agent_kit.db"))
    assert reset_calls == []


# --- endpoints ---


def test_get_settings_returns_defaults(client):
    r = client.get("/api/v1/settings")
    assert r.status_code == 200
    assert r.json()["respec_threshold"] == 12


def test_put_settings_merges_a_partial_patch(client):
    save_settings(PlaygroundSettings(gm_model="keep-me"))
    r = client.put("/api/v1/settings", json={"respec_threshold": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["respec_threshold"] == 5
    assert body["gm_model"] == "keep-me"


def test_put_settings_persists_across_reads(client):
    client.put("/api/v1/settings", json={"suggestions_enabled": False})
    assert client.get("/api/v1/settings").json()["suggestions_enabled"] is False


def test_put_settings_rejects_out_of_range_threshold(client):
    assert client.put("/api/v1/settings", json={"respec_threshold": 0}).status_code == 422
    assert client.put("/api/v1/settings", json={"respec_threshold": 51}).status_code == 422


def test_put_settings_applies_to_the_environment(client):
    client.put("/api/v1/settings", json={"provider_url": "http://api-set:1/v1"})
    assert os.environ["AGENT_KIT_PROVIDER_URL"] == "http://api-set:1/v1"
