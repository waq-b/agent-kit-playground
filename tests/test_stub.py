import pytest
from pydantic import BaseModel

from agent_kit.errors import NoFixtureError
from agent_kit.stub_store import StubStore


class Out(BaseModel):
    x: str


def test_register_get_clear():
    store = StubStore()
    store.register("a", Out(x="y"))
    assert store.get("a").x == "y"
    store.clear()
    with pytest.raises(NoFixtureError):
        store.get("a")


def test_no_fixture_error_message_contains_agent_name_and_text():
    store = StubStore()
    with pytest.raises(NoFixtureError) as exc_info:
        store.get("missing_agent")
    message = str(exc_info.value)
    assert "missing_agent" in message
    assert "no fixture registered" in message
