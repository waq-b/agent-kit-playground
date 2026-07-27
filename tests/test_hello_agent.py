import pytest
from pydantic import ValidationError

import agent_kit
from agent_kit.agents.models.hello import HelloOutput
from agent_kit.registry import get_registry


def test_hello_agent_registered_at_startup(isolated_registries):
    listing = get_registry().list()
    assert {"name": "hello", "description": "Greets a person by name"} in listing


def test_stub_returns_hello_output_with_non_empty_greeting(isolated_registries):
    result = agent_kit.run_agent("hello", {"name": "Alice"})
    assert isinstance(result, HelloOutput)
    assert result.greeting != ""


def test_empty_name_raises_validation_error(isolated_registries):
    with pytest.raises(ValidationError):
        agent_kit.run_agent("hello", {"name": ""})
