"""The model provider registry: storage validation, resolution, the API, and
that api_key never crosses the wire."""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import agent_kit.builder as builder_module
import agent_kit.gm as gm_module
from agent_kit.builder import BuilderPaths, check_model_reachable
from agent_kit.gm import GMSynthesis
from agent_kit.playground.app import app
from agent_kit.settings import (
    ModelProviderEntry,
    PlaygroundSettings,
    load_settings,
    resolve_model_provider,
    save_settings,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_KIT_DATA_DIR", str(tmp_path / "agent_kit_data"))
    monkeypatch.setattr(
        builder_module, "DEFAULT_PATHS", BuilderPaths(data_dir=tmp_path / "agent_kit_data")
    )
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


# --- ModelProviderEntry validation ---


def test_local_entry_ignores_any_url_or_key_passed_to_it():
    entry = ModelProviderEntry(model_id="llama3.1:8b", kind="local", base_url="x", api_key="y")
    assert entry.base_url is None
    assert entry.api_key is None


def test_frontier_entry_requires_a_base_url():
    with pytest.raises(ValueError, match="base URL"):
        ModelProviderEntry(model_id="gpt-4o", kind="frontier", api_key="sk-x")


def test_frontier_entry_requires_an_api_key():
    with pytest.raises(ValueError, match="API key"):
        ModelProviderEntry(model_id="gpt-4o", kind="frontier", base_url="https://api.openai.com/v1")


def test_frontier_entry_rejects_whitespace_only_fields():
    with pytest.raises(ValueError):
        ModelProviderEntry(
            model_id="gpt-4o", kind="frontier", base_url="   ", api_key="sk-x"
        )


def test_model_id_cannot_be_empty():
    with pytest.raises(ValueError):
        ModelProviderEntry(model_id="", kind="local")


# --- resolve_model_provider ---


def test_unregistered_model_resolves_to_the_shared_local_provider():
    resolved = resolve_model_provider("whatever-model")
    assert resolved.is_frontier is False
    assert resolved.base_url == "http://localhost:11434/v1"
    assert resolved.api_key == "ollama"


def test_registered_local_model_also_resolves_to_the_shared_local_provider():
    save_settings(PlaygroundSettings(
        provider_url="http://elsewhere:9999/v1",
        models=[ModelProviderEntry(model_id="llama3.1:8b", kind="local")],
    ))
    resolved = resolve_model_provider("llama3.1:8b")
    assert resolved.is_frontier is False
    assert resolved.base_url == "http://elsewhere:9999/v1"


def test_registered_frontier_model_resolves_to_its_own_provider():
    save_settings(PlaygroundSettings(models=[
        ModelProviderEntry(
            model_id="gpt-4o", kind="frontier",
            base_url="https://api.openai.com/v1", api_key="sk-abc",
        )
    ]))
    resolved = resolve_model_provider("gpt-4o")
    assert resolved.is_frontier is True
    assert resolved.base_url == "https://api.openai.com/v1"
    assert resolved.api_key == "sk-abc"


def test_resolution_is_read_fresh_on_every_call():
    assert resolve_model_provider("gpt-4o").is_frontier is False
    settings = load_settings()
    settings.models = [ModelProviderEntry(
        model_id="gpt-4o", kind="frontier", base_url="https://api.openai.com/v1", api_key="k"
    )]
    save_settings(settings)
    assert resolve_model_provider("gpt-4o").is_frontier is True


# --- endpoints ---


def test_list_models_starts_empty(client):
    assert client.get("/api/v1/models").json() == []


def test_create_local_model(client):
    r = client.post("/api/v1/models", json={"model_id": "llama3.1:8b", "kind": "local"})
    assert r.status_code == 201
    body = r.json()
    assert body == {
        "model_id": "llama3.1:8b", "label": "llama3.1:8b", "kind": "local",
        "base_url": None, "has_api_key": False,
    }


def test_create_frontier_model_never_echoes_the_key(client):
    r = client.post("/api/v1/models", json={
        "model_id": "gpt-4o", "label": "GPT-4o", "kind": "frontier",
        "base_url": "https://api.openai.com/v1", "api_key": "sk-supersecret",
    })
    assert r.status_code == 201
    assert "sk-supersecret" not in r.text
    assert r.json()["has_api_key"] is True


def test_create_frontier_model_without_base_url_is_422(client):
    r = client.post("/api/v1/models", json={"model_id": "gpt-4o", "kind": "frontier"})
    assert r.status_code == 422


def test_duplicate_model_id_is_409(client):
    client.post("/api/v1/models", json={"model_id": "dup", "kind": "local"})
    r = client.post("/api/v1/models", json={"model_id": "dup", "kind": "local"})
    assert r.status_code == 409


def test_list_models_never_leaks_api_keys(client):
    client.post("/api/v1/models", json={
        "model_id": "gpt-4o", "kind": "frontier",
        "base_url": "https://api.openai.com/v1", "api_key": "sk-supersecret",
    })
    r = client.get("/api/v1/models")
    assert "sk-supersecret" not in r.text


def test_settings_endpoints_never_include_the_model_registry(client):
    client.post("/api/v1/models", json={
        "model_id": "gpt-4o", "kind": "frontier",
        "base_url": "https://api.openai.com/v1", "api_key": "sk-supersecret",
    })
    get_body = client.get("/api/v1/settings")
    assert "models" not in get_body.json()
    assert "sk-supersecret" not in get_body.text

    put_body = client.put("/api/v1/settings", json={"gm_model": "gpt-4o"})
    assert "models" not in put_body.json()
    assert "sk-supersecret" not in put_body.text

    # And the key really did persist server-side, PUT /settings didn't drop it.
    assert load_settings().models[0].api_key == "sk-supersecret"


def test_delete_model(client):
    client.post("/api/v1/models", json={"model_id": "temp", "kind": "local"})
    assert client.delete("/api/v1/models/temp").status_code == 200
    assert client.get("/api/v1/models").json() == []


def test_delete_unknown_model_is_404(client):
    assert client.delete("/api/v1/models/nope").status_code == 404


# --- builder.check_model_reachable ---


def test_check_model_reachable_uses_frontier_credentials(monkeypatch):
    save_settings(PlaygroundSettings(models=[
        ModelProviderEntry(
            model_id="gpt-4o", kind="frontier",
            base_url="https://api.openai.com/v1", api_key="sk-abc",
        )
    ]))

    captured = {}

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"id": "gpt-4o"}]}

    def _fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResponse()

    monkeypatch.setattr(builder_module.httpx, "get", _fake_get)
    result = check_model_reachable("gpt-4o")

    assert captured["url"] == "https://api.openai.com/v1/models"
    assert captured["headers"] == {"Authorization": "Bearer sk-abc"}
    assert result["available"] is True


def test_check_model_reachable_sends_no_auth_header_for_local():
    captured = {}

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": []}

    def _fake_get(url, headers=None, timeout=None):
        captured["headers"] = headers
        return _FakeResponse()

    import agent_kit.builder as b
    orig = b.httpx.get
    b.httpx.get = _fake_get
    try:
        check_model_reachable("qwen2.5:14b")
    finally:
        b.httpx.get = orig

    assert captured["headers"] is None


# --- gm.py resolution ---


def test_gm_uses_frontier_credentials_for_a_registered_gm_model(monkeypatch):
    save_settings(PlaygroundSettings(models=[
        ModelProviderEntry(
            model_id="gpt-4o", kind="frontier",
            base_url="https://api.openai.com/v1", api_key="sk-gm-key",
        )
    ]))
    monkeypatch.setenv("AGENT_KIT_GM_MODEL", "gpt-4o")
    monkeypatch.delenv("AGENT_KIT_GM_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_KIT_GM_PROVIDER", raising=False)

    with patch("agent_kit.gm.Agent"), \
         patch("pydantic_ai.models.openai.OpenAIChatModel"), \
         patch("pydantic_ai.providers.openai.OpenAIProvider") as mock_provider_cls:
        gm_module._build_gm_agent()

    _, kwargs = mock_provider_cls.call_args
    assert kwargs["base_url"] == "https://api.openai.com/v1"
    assert kwargs["api_key"] == "sk-gm-key"


def test_gm_api_key_env_override_still_wins_over_the_registry(monkeypatch):
    """AGENT_KIT_GM_API_KEY is an existing, documented override — it must keep
    taking precedence even when the gm_model also happens to be registered."""
    save_settings(PlaygroundSettings(models=[
        ModelProviderEntry(
            model_id="gpt-4o", kind="frontier",
            base_url="https://api.openai.com/v1", api_key="sk-from-registry",
        )
    ]))
    monkeypatch.setenv("AGENT_KIT_GM_MODEL", "gpt-4o")
    monkeypatch.setenv("AGENT_KIT_GM_API_KEY", "sk-from-env-override")
    monkeypatch.delenv("AGENT_KIT_GM_PROVIDER", raising=False)

    with patch("agent_kit.gm.Agent"), \
         patch("pydantic_ai.models.openai.OpenAIChatModel"), \
         patch("pydantic_ai.providers.openai.OpenAIProvider") as mock_provider_cls:
        gm_module._build_gm_agent()

    _, kwargs = mock_provider_cls.call_args
    assert kwargs["api_key"] == "sk-from-env-override"
