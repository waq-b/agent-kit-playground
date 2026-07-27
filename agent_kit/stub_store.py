"""StubStore — the in-process singleton store of fixture data used in Stub_Mode."""

from __future__ import annotations

from pydantic import BaseModel

from agent_kit.errors import NoFixtureError


class StubStore:
    def __init__(self) -> None:
        self._store: dict[str, BaseModel] = {}

    def register(self, agent_name: str, fixture: BaseModel) -> None:
        self._store[agent_name] = fixture

    def get(self, agent_name: str) -> BaseModel:
        fixture = self._store.get(agent_name)
        if fixture is None:
            raise NoFixtureError(f"no fixture registered for agent '{agent_name}'")
        return fixture

    def clear(self) -> None:
        self._store.clear()


_stub_store = StubStore()


def get_stub_store() -> StubStore:
    return _stub_store
