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

    def replace(self, definition: AgentDefinition) -> None:
        """Register a definition, overwriting any existing entry with the same name.

        Unlike register(), never raises DuplicateAgentError — used by the
        Agent Builder (v0.3) to let a user-edited copy of a built-in agent
        take precedence over the pristine original during a registry reload.
        """
        self._store[definition.name] = definition

    def remove(self, name: str) -> None:
        """Remove an entry if present; a no-op if the name isn't registered.

        Used by the Agent Builder (v0.3) to apply "deleted agent" tombstones
        after a reload — a built-in agent otherwise always reappears from the
        pristine package directory on every _initialise() call, so a delete
        of a never-edited built-in needs an explicit post-load removal step,
        not just deleting a user-directory override file that never existed.
        """
        self._store.pop(name, None)

    def list(self) -> list[dict[str, str]]:
        return [{"name": d.name, "description": d.description} for d in self._store.values()]

    def clear(self) -> None:
        self._store.clear()


_registry = AgentRegistry()


def get_registry() -> AgentRegistry:
    return _registry
