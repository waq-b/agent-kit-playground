"""ToolRegistry — maps tool names (as referenced in YAML) to Python callables."""

from __future__ import annotations

from typing import Callable

from agent_kit.errors import UnknownToolError


class ToolRegistry:
    def __init__(self) -> None:
        self._store: dict[str, Callable] = {}

    def register(self, name: str, fn: Callable) -> None:
        self._store[name] = fn

    def get(self, name: str) -> Callable:
        fn = self._store.get(name)
        if fn is None:
            raise UnknownToolError(f"unknown tool '{name}'")
        return fn

    def list_names(self) -> list[str]:
        return list(self._store.keys())

    def clear(self) -> None:
        self._store.clear()


_tool_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    return _tool_registry
