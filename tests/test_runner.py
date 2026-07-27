from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from agent_kit.definition import AgentDefinition
from agent_kit.errors import NoFixtureError, TemperatureRangeError, TypeMismatchError
from agent_kit.runner import Runner
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
