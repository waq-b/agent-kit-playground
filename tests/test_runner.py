from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel
from pydantic_ai.messages import ToolCallPart

from agent_kit.card_definition import CardDefinition
from agent_kit.card_store import CardStore
from agent_kit.class_definition import ClassDefinition
from agent_kit.definition import AgentDefinition
from agent_kit.errors import NoFixtureError, TemperatureRangeError, TypeMismatchError
from agent_kit.runner import Runner
from agent_kit.errors import GMUnavailableError
from agent_kit.gm import GMSynthesis
from agent_kit.stat_effects import PromptBand, RuntimeCurve, StatDefinition
from agent_kit.stat_mapping import compute_temperature
from agent_kit.stub_store import get_stub_store

AGENT_NAME = "runner_test_agent"


class Out(BaseModel):
    greeting: str


class WrongOut(BaseModel):
    other: str


def make_definition(temperature: float = 0.7) -> AgentDefinition:
    return AgentDefinition(
        name=AGENT_NAME, description="d", system_prompt="sp", model="qwen2.5:14b",
        temperature=temperature, tools=[], output_model=Out, source_path=Path("x.yaml"),
    )


@pytest.fixture(autouse=True)
def _clear_stub_store():
    get_stub_store().clear()
    yield
    get_stub_store().clear()


def test_stub_path_returns_fixture():
    get_stub_store().register(AGENT_NAME, Out(greeting="hi"))
    result = Runner().execute(make_definition(), {"name": "x"})
    assert isinstance(result, Out)
    assert result.greeting == "hi"


def test_no_fixture_error_when_no_fixture_registered():
    with pytest.raises(NoFixtureError):
        Runner().execute(make_definition(), {"name": "x"})


def test_type_mismatch_error_on_wrong_fixture_type():
    get_stub_store().register(AGENT_NAME, WrongOut(other="y"))
    with pytest.raises(TypeMismatchError):
        Runner().execute(make_definition(), {"name": "x"})


def test_temperature_range_error_raised_before_any_network_call():
    with patch("agent_kit.runner.Agent") as mock_agent:
        with pytest.raises(TemperatureRangeError):
            Runner().execute(make_definition(temperature=5.0), {"name": "x"})
        mock_agent.assert_not_called()


def test_live_path_is_not_invoked_in_stub_mode():
    get_stub_store().register(AGENT_NAME, Out(greeting="hi"))
    with patch("agent_kit.runner.Agent") as mock_agent:
        Runner().execute(make_definition(), {"name": "x"})
        mock_agent.assert_not_called()


def _fake_run_result(output: BaseModel, tool_calls: list[ToolCallPart] | None = None) -> MagicMock:
    result = MagicMock()
    if tool_calls:
        message = MagicMock()
        message.parts = tool_calls
        result.all_messages.return_value = [message]
    else:
        result.all_messages.return_value = []
    result.response.parts = []
    result.output = output
    return result


def test_last_tools_used_empty_in_stub_mode():
    get_stub_store().register(AGENT_NAME, Out(greeting="hi"))
    runner = Runner()
    runner.execute(make_definition(), {"name": "x"})
    assert runner.last_tools_used == []


def test_card_none_agent_calls_pydantic_ai_agent_with_none_kwargs(monkeypatch):
    """Regression guard: for any AgentDefinition without a card, the new
    retries/tool_timeout/max_concurrency kwargs must stay None — byte-for-byte
    the same call shape as before the Character Layer existed."""
    monkeypatch.delenv("STUB_AI_PROVIDERS", raising=False)

    with patch("agent_kit.runner.Agent") as mock_agent_cls, \
         patch("agent_kit.runner.OpenAIChatModel"), \
         patch("agent_kit.runner.OpenAIProvider"):
        mock_agent_cls.return_value.run_sync.return_value = _fake_run_result(Out(greeting="hi"))
        Runner().execute(make_definition(), {"name": "x"})

    _, kwargs = mock_agent_cls.call_args
    assert kwargs["retries"] is None
    assert kwargs["tool_timeout"] is None
    assert kwargs["max_concurrency"] is None
    assert kwargs["model_settings"] == {"temperature": 0.7}


def test_unregistered_model_uses_the_local_provider(monkeypatch, tmp_path):
    """Regression guard: a model with no registry entry — the only case that
    existed before the model registry — still resolves to the shared local
    provider_url with the fixed placeholder key, unchanged."""
    monkeypatch.delenv("STUB_AI_PROVIDERS", raising=False)
    monkeypatch.setenv("AGENT_KIT_DATA_DIR", str(tmp_path / "agent_kit_data"))

    with patch("agent_kit.runner.Agent") as mock_agent_cls, \
         patch("agent_kit.runner.OpenAIChatModel"), \
         patch("agent_kit.runner.OpenAIProvider") as mock_provider_cls:
        mock_agent_cls.return_value.run_sync.return_value = _fake_run_result(Out(greeting="hi"))
        Runner().execute(make_definition(), {"name": "x"})

    _, kwargs = mock_provider_cls.call_args
    assert kwargs["base_url"] == "http://localhost:11434/v1"
    assert kwargs["api_key"] == "ollama"


def test_frontier_registered_model_routes_to_its_own_provider(monkeypatch, tmp_path):
    """A model registered as frontier is what actually makes 'frontier' mean
    something: the Runner must call out to *that* provider, not the local one."""
    from agent_kit.settings import ModelProviderEntry, PlaygroundSettings, save_settings

    monkeypatch.delenv("STUB_AI_PROVIDERS", raising=False)
    monkeypatch.setenv("AGENT_KIT_DATA_DIR", str(tmp_path / "agent_kit_data"))
    save_settings(PlaygroundSettings(models=[
        ModelProviderEntry(
            model_id="gpt-4o", kind="frontier",
            base_url="https://api.openai.com/v1", api_key="sk-test-key",
        )
    ]))
    definition = AgentDefinition(
        name=AGENT_NAME, description="d", system_prompt="sp", model="gpt-4o",
        temperature=0.7, tools=[], output_model=Out, source_path=Path("x.yaml"),
    )

    with patch("agent_kit.runner.Agent") as mock_agent_cls, \
         patch("agent_kit.runner.OpenAIChatModel"), \
         patch("agent_kit.runner.OpenAIProvider") as mock_provider_cls:
        mock_agent_cls.return_value.run_sync.return_value = _fake_run_result(Out(greeting="hi"))
        Runner().execute(definition, {"name": "x"})

    _, kwargs = mock_provider_cls.call_args
    assert kwargs["base_url"] == "https://api.openai.com/v1"
    assert kwargs["api_key"] == "sk-test-key"


def make_carded_definition(stat_value: int = 60, curve: RuntimeCurve | None = None) -> AgentDefinition:
    stat = StatDefinition(
        value=stat_value,
        prompt_effect=(PromptBand("low", "You are reserved."), PromptBand("high", "You are warm.")),
        runtime_effect={"temperature": curve or RuntimeCurve(at_0=0.0, at_100=0.0)},
    )
    main_class = ClassDefinition(
        name="greeter", title="Greeter", description="d",
        stats={"warmth": stat}, source_path=Path("x.yaml"),
    )
    card = CardDefinition(
        title="Greeter", backstory="", portrait="", main_class=main_class, sub_class=None,
        class_stats={"warmth": stat_value},
        base_stats={"accuracy": 100, "insight": 50, "speed": 100, "reliability": 100},
        unlock_table=(), starting_level=1, starting_xp=0,
    )
    return AgentDefinition(
        name=AGENT_NAME, description="d", system_prompt="sp", model="qwen2.5:14b",
        temperature=0.7, tools=[], output_model=Out, source_path=Path("x.yaml"), card=card,
    )


def _run_carded(definition, store, monkeypatch, gm_result=None, gm_error=None):
    """Run a card-bearing agent live with the model and GM both patched out."""
    import agent_kit.gm as gm_module

    if gm_error is not None:
        def _fake_synth(*args, **kwargs):
            raise gm_error
    else:
        def _fake_synth(*args, **kwargs):
            return gm_result

    monkeypatch.setattr(gm_module, "synthesize_traits", _fake_synth)

    with patch("agent_kit.runner.get_card_store", return_value=store), \
         patch("agent_kit.runner.Agent") as mock_agent_cls, \
         patch("agent_kit.runner.OpenAIChatModel"), \
         patch("agent_kit.runner.OpenAIProvider"):
        mock_agent_cls.return_value.run_sync.return_value = _fake_run_result(Out(greeting="hi"))
        runner = Runner()
        runner.execute(definition, {"name": "x"})
    return runner, mock_agent_cls


def test_card_present_agent_receives_stat_derived_kwargs(monkeypatch):
    monkeypatch.delenv("STUB_AI_PROVIDERS", raising=False)

    runner, mock_agent_cls = _run_carded(
        make_carded_definition(), CardStore(":memory:"), monkeypatch,
        gm_result=GMSynthesis(trait_paragraph="You are warm."),
    )

    _, kwargs = mock_agent_cls.call_args
    assert kwargs["retries"] == 5  # accuracy=100 -> compute_retries(100)
    assert kwargs["max_concurrency"] == 4  # speed=100 -> compute_max_concurrency(100)
    # zero-delta curve, so the base-stat temperature is unchanged
    assert kwargs["model_settings"]["temperature"] == compute_temperature(0.7, reliability=100)


def test_class_stat_runtime_deltas_are_layered_onto_base_params(monkeypatch):
    """The core v0.4 behaviour: a class stat's curve shifts the base-stat value."""
    monkeypatch.delenv("STUB_AI_PROVIDERS", raising=False)

    base_temperature = compute_temperature(0.7, reliability=100)
    # warmth=100 with at_100=+0.5 -> a +0.5 delta on top of the base value
    definition = make_carded_definition(stat_value=100, curve=RuntimeCurve(at_0=0.0, at_100=0.5))

    _, mock_agent_cls = _run_carded(
        definition, CardStore(":memory:"), monkeypatch,
        gm_result=GMSynthesis(trait_paragraph="You are warm."),
    )

    _, kwargs = mock_agent_cls.call_args
    assert kwargs["model_settings"]["temperature"] == pytest.approx(base_temperature + 0.5)


def test_trait_paragraph_is_appended_to_system_prompt(monkeypatch):
    monkeypatch.delenv("STUB_AI_PROVIDERS", raising=False)

    runner, mock_agent_cls = _run_carded(
        make_carded_definition(), CardStore(":memory:"), monkeypatch,
        gm_result=GMSynthesis(trait_paragraph="You are relentlessly warm."),
    )

    _, kwargs = mock_agent_cls.call_args
    assert kwargs["system_prompt"].startswith("sp")  # author's own prompt is preserved verbatim
    assert "Character traits:" in kwargs["system_prompt"]
    assert "You are relentlessly warm." in kwargs["system_prompt"]
    assert runner.last_trait_paragraph == "You are relentlessly warm."
    assert runner.last_traits_stale is False


def test_gm_synthesis_is_cached_and_not_repeated(monkeypatch):
    monkeypatch.delenv("STUB_AI_PROVIDERS", raising=False)
    store = CardStore(":memory:")
    definition = make_carded_definition()

    calls = []

    import agent_kit.gm as gm_module

    def _counting_synth(*args, **kwargs):
        calls.append(1)
        return GMSynthesis(trait_paragraph="Synthesized once.")

    monkeypatch.setattr(gm_module, "synthesize_traits", _counting_synth)

    for _ in range(3):
        with patch("agent_kit.runner.get_card_store", return_value=store), \
             patch("agent_kit.runner.Agent") as mock_agent_cls, \
             patch("agent_kit.runner.OpenAIChatModel"), \
             patch("agent_kit.runner.OpenAIProvider"):
            mock_agent_cls.return_value.run_sync.return_value = _fake_run_result(Out(greeting="hi"))
            Runner().execute(definition, {"name": "x"})

    assert len(calls) == 1, "GM must only be called once while the band signature is unchanged"


def test_gm_suggestion_is_recorded_but_never_auto_applied(monkeypatch):
    monkeypatch.delenv("STUB_AI_PROVIDERS", raising=False)
    store = CardStore(":memory:")
    definition = make_carded_definition()

    _run_carded(
        definition, store, monkeypatch,
        gm_result=GMSynthesis(
            trait_paragraph="p", conflicts=["clash"], suggested_system_prompt="a better prompt"
        ),
    )

    suggestions = store.list_suggestions("pending")
    assert len(suggestions) == 1
    assert suggestions[0].suggested_system_prompt == "a better prompt"
    # the definition's own prompt is untouched — approval is a separate, human step
    assert definition.system_prompt == "sp"


def test_gm_failure_with_warm_cache_reuses_it_and_applies_debuff(monkeypatch):
    monkeypatch.delenv("STUB_AI_PROVIDERS", raising=False)
    store = CardStore(":memory:")
    definition = make_carded_definition()

    # first run succeeds and caches
    _run_carded(definition, store, monkeypatch, gm_result=GMSynthesis(trait_paragraph="Good paragraph."))
    store.mark_traits_stale(definition.name)  # force a re-synthesis attempt

    runner, mock_agent_cls = _run_carded(
        definition, store, monkeypatch, gm_error=GMUnavailableError("GM down")
    )

    assert runner.last_trait_paragraph == "Good paragraph."  # last good prompt reused
    assert runner.last_traits_stale is True
    assert [t.agent_name for t in store.list_stale_agents()] == [definition.name]
    assert "Good paragraph." in mock_agent_cls.call_args[1]["system_prompt"]


def test_gm_failure_with_cold_cache_still_runs_via_deterministic_fallback(monkeypatch):
    monkeypatch.delenv("STUB_AI_PROVIDERS", raising=False)
    store = CardStore(":memory:")
    definition = make_carded_definition(stat_value=100)  # -> "high" band

    runner, mock_agent_cls = _run_carded(
        definition, store, monkeypatch, gm_error=GMUnavailableError("GM down")
    )

    # the run completes rather than failing, using the crude concatenation
    assert runner.last_trait_paragraph == "You are warm."
    assert runner.last_traits_stale is True
    # and it still lands in the respec queue despite never having a good paragraph
    assert [t.agent_name for t in store.list_stale_agents()] == [definition.name]


def test_stub_mode_uses_fallback_and_never_calls_the_gm(monkeypatch):
    """Stub mode must stay fully offline — no GM, no model, no network."""
    monkeypatch.setenv("STUB_AI_PROVIDERS", "1")
    get_stub_store().register(AGENT_NAME, Out(greeting="hi"))

    import agent_kit.gm as gm_module

    def _boom(*args, **kwargs):
        raise AssertionError("the GM must never be called in stub mode")

    monkeypatch.setattr(gm_module, "synthesize_traits", _boom)

    runner = Runner()
    runner.execute(make_carded_definition(), {"name": "x"})
    assert runner.last_traits_stale is False


def test_last_tools_used_populated_from_tool_call_parts(monkeypatch):
    monkeypatch.delenv("STUB_AI_PROVIDERS", raising=False)

    tool_call = ToolCallPart(tool_name="fetch_rss_feed", args={}, tool_call_id="call_1")

    with patch("agent_kit.runner.Agent") as mock_agent_cls, \
         patch("agent_kit.runner.OpenAIChatModel"), \
         patch("agent_kit.runner.OpenAIProvider"):
        mock_agent_cls.return_value.run_sync.return_value = _fake_run_result(
            Out(greeting="hi"), tool_calls=[tool_call]
        )
        runner = Runner()
        runner.execute(make_definition(), {"name": "x"})

    assert runner.last_tools_used == ["fetch_rss_feed"]
