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


def test_card_present_agent_receives_stat_derived_kwargs(monkeypatch):
    monkeypatch.delenv("STUB_AI_PROVIDERS", raising=False)

    main_class = ClassDefinition(name="greeter", title="Greeter", description="d", stats={"warmth": 60}, source_path=Path("x.yaml"))
    card = CardDefinition(
        title="Greeter", backstory="", portrait="", main_class=main_class, sub_class=None,
        class_stats={"warmth": 60},
        base_stats={"accuracy": 100, "insight": 50, "speed": 100, "reliability": 100},
        unlock_table=(), starting_level=1, starting_xp=0,
    )
    definition = AgentDefinition(
        name=AGENT_NAME, description="d", system_prompt="sp", model="qwen2.5:14b",
        temperature=0.7, tools=[], output_model=Out, source_path=Path("x.yaml"), card=card,
    )
    fake_store = CardStore(":memory:")

    with patch("agent_kit.runner.get_card_store", return_value=fake_store), \
         patch("agent_kit.runner.Agent") as mock_agent_cls, \
         patch("agent_kit.runner.OpenAIChatModel"), \
         patch("agent_kit.runner.OpenAIProvider"):
        mock_agent_cls.return_value.run_sync.return_value = _fake_run_result(Out(greeting="hi"))
        Runner().execute(definition, {"name": "x"})

    _, kwargs = mock_agent_cls.call_args
    assert kwargs["retries"] == 5  # accuracy=100 -> compute_retries(100)
    assert kwargs["max_concurrency"] == 4  # speed=100 -> compute_max_concurrency(100)
    assert kwargs["model_settings"]["temperature"] == compute_temperature(0.7, reliability=100)


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
