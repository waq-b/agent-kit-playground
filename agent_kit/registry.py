"""AgentRegistry — the in-process singleton store of registered AgentDefinitions."""

from __future__ import annotations

from agent_kit.definition import AgentDefinition
from agent_kit.errors import AgentNotFoundError, DuplicateAgentError


class AgentRegistry:
    def __init__(self) -> None:
        self._store: dict[str, AgentDefinition] = {}

    def register(self, definition: AgentDefinition) -> None:
        existing = self._store.get(definition.name)
        if existing is not None:
            raise DuplicateAgentError(
                f"agent '{definition.name}' is already registered "
                f"(existing: {existing.source_path}, conflicting: {definition.source_path})"
            )
        self._store[definition.name] = definition

    def get(self, name: str) -> AgentDefinition:
        definition = self._store.get(name)
        if definition is None:
            raise AgentNotFoundError(f"agent '{name}' is not registered")
        return definition

    def list(self) -> list[dict[str, str]]:
        return [{"name": d.name, "description": d.description} for d in self._store.values()]

    def clear(self) -> None:
        self._store.clear()


_registry = AgentRegistry()


def get_registry() -> AgentRegistry:
    return _registry
