from pathlib import Path

import pytest
from pydantic import BaseModel

from agent_kit.definition import AgentDefinition
from agent_kit.errors import AgentNotFoundError, DuplicateAgentError
from agent_kit.registry import AgentRegistry


class Out(BaseModel):
    x: str


def make(name: str, path: str = "a.yaml") -> AgentDefinition:
    return AgentDefinition(
        name=name, description="d", system_prompt="sp", model="m",
        temperature=0.5, tools=[], output_model=Out, source_path=Path(path),
    )


def test_register_get_list_clear():
    r = AgentRegistry()
    r.register(make("a"))
    assert r.get("a").name == "a"
    assert r.list() == [{"name": "a", "description": "d"}]
    r.clear()
    assert r.list() == []


def test_duplicate_agent_error_on_second_registration():
    r = AgentRegistry()
    r.register(make("a", "a.yaml"))
    with pytest.raises(DuplicateAgentError):
        r.register(make("a", "b.yaml"))


def test_agent_not_found_error_on_unknown_name():
    r = AgentRegistry()
    with pytest.raises(AgentNotFoundError) as exc_info:
        r.get("nope")
    assert "nope" in str(exc_info.value)


def test_list_returns_exactly_name_and_description_per_entry():
    r = AgentRegistry()
    r.register(make("a"))
    r.register(make("b"))
    listing = r.list()
    assert len(listing) == 2
    for entry in listing:
        assert set(entry.keys()) == {"name", "description"}
