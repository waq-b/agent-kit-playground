"""ClassRegistry — the in-process singleton store of registered ClassDefinitions."""

from __future__ import annotations

from agent_kit.class_definition import ClassDefinition
from agent_kit.errors import ClassNotFoundError, DuplicateClassError


class ClassRegistry:
    def __init__(self) -> None:
        self._store: dict[str, ClassDefinition] = {}

    def register(self, definition: ClassDefinition) -> None:
        existing = self._store.get(definition.name)
        if existing is not None:
            raise DuplicateClassError(
                f"class '{definition.name}' is already registered "
                f"(existing: {existing.source_path}, conflicting: {definition.source_path})"
            )
        self._store[definition.name] = definition

    def get(self, name: str) -> ClassDefinition:
        definition = self._store.get(name)
        if definition is None:
            raise ClassNotFoundError(f"class '{name}' is not registered")
        return definition

    def replace(self, definition: ClassDefinition) -> None:
        """Register a definition, overwriting any existing entry with the same name.

        Unlike register(), never raises DuplicateClassError — used by the
        Agent Builder (v0.3) to let a user-edited copy of a built-in class
        take precedence over the pristine original during a registry reload.
        """
        self._store[definition.name] = definition

    def list(self) -> list[dict[str, str]]:
        return [{"name": d.name, "title": d.title} for d in self._store.values()]

    def clear(self) -> None:
        self._store.clear()


_class_registry = ClassRegistry()


def get_class_registry() -> ClassRegistry:
    return _class_registry
