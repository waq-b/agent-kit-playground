import pytest

import agent_kit.gm as gm_module
from agent_kit.errors import GMUnavailableError
from agent_kit.gm import GMSynthesis, gm_configuration, synthesize_traits
from agent_kit.stat_effects import PromptBand

BANDS = {"warmth": PromptBand(label="high", text="You are warm.")}


def test_gm_configuration_defaults_to_local(monkeypatch):
    for var in ("AGENT_KIT_GM_MODEL", "AGENT_KIT_GM_PROVIDER", "AGENT_KIT_GM_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    config = gm_configuration()
    assert config["provider"] == "ollama"
    assert config["model"] == "qwen2.5:14b"
    assert config["api_key"] is None


def test_gm_configuration_reads_env_vars(monkeypatch):
    monkeypatch.setenv("AGENT_KIT_GM_PROVIDER", "anthropic")
    monkeypatch.setenv("AGENT_KIT_GM_MODEL", "claude-sonnet-4-5")
    monkeypatch.setenv("AGENT_KIT_GM_API_KEY", "test-key")
    config = gm_configuration()
    assert config == {"provider": "anthropic", "model": "claude-sonnet-4-5", "api_key": "test-key"}


def test_synthesize_traits_refuses_in_stub_mode(monkeypatch):
    """Stub mode must never reach a model — the offline-test guarantee."""
    monkeypatch.setenv("STUB_AI_PROVIDERS", "1")
    with pytest.raises(GMUnavailableError):
        synthesize_traits("hello", "sp", BANDS)


def test_synthesize_traits_empty_bands_returns_empty_without_calling_model(monkeypatch):
    monkeypatch.delenv("STUB_AI_PROVIDERS", raising=False)

    def _boom():
        raise AssertionError("GM model must not be constructed when there are no bands")

    monkeypatch.setattr(gm_module, "_build_gm_agent", _boom)
    assert synthesize_traits("hello", "sp", {}).trait_paragraph == ""


def test_paid_provider_without_api_key_raises(monkeypatch):
    monkeypatch.delenv("STUB_AI_PROVIDERS", raising=False)
    monkeypatch.setenv("AGENT_KIT_GM_PROVIDER", "anthropic")
    monkeypatch.delenv("AGENT_KIT_GM_API_KEY", raising=False)

    with pytest.raises(GMUnavailableError, match="AGENT_KIT_GM_API_KEY"):
        synthesize_traits("hello", "sp", BANDS)


def test_unsupported_provider_raises(monkeypatch):
    monkeypatch.delenv("STUB_AI_PROVIDERS", raising=False)
    monkeypatch.setenv("AGENT_KIT_GM_PROVIDER", "not-a-real-provider")

    with pytest.raises(GMUnavailableError, match="unsupported GM provider"):
        synthesize_traits("hello", "sp", BANDS)


def test_model_call_failure_is_wrapped_as_gm_unavailable(monkeypatch):
    monkeypatch.delenv("STUB_AI_PROVIDERS", raising=False)

    class _FailingAgent:
        def run_sync(self, prompt):
            raise ConnectionError("no route to host")

    monkeypatch.setattr(gm_module, "_build_gm_agent", lambda: _FailingAgent())

    with pytest.raises(GMUnavailableError, match="GM synthesis failed"):
        synthesize_traits("hello", "sp", BANDS)


def test_successful_synthesis_returns_output(monkeypatch):
    monkeypatch.delenv("STUB_AI_PROVIDERS", raising=False)

    expected = GMSynthesis(trait_paragraph="You are a warm greeter.", conflicts=["a clash"])

    class _Result:
        output = expected

    class _OKAgent:
        def run_sync(self, prompt):
            # the fragments and the agent's own system prompt both reach the GM
            assert "You are warm." in prompt
            assert "the agent's own system prompt" in prompt.lower()
            return _Result()

    monkeypatch.setattr(gm_module, "_build_gm_agent", lambda: _OKAgent())

    result = synthesize_traits("hello", "sp", BANDS)
    assert result.trait_paragraph == "You are a warm greeter."
    assert result.conflicts == ["a clash"]


def test_suggested_system_prompt_defaults_to_none():
    assert GMSynthesis(trait_paragraph="x").suggested_system_prompt is None
