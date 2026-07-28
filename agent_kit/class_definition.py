"""ClassDefinition — a reusable, named bundle of class-specific stats."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_kit.base_stats import BASE_STAT_NAMES, DEFAULT_BASE_STAT_VALUE
from agent_kit.stat_effects import StatDefinition

__all__ = ["BASE_STAT_NAMES", "DEFAULT_BASE_STAT_VALUE", "ClassDefinition"]


@dataclass(frozen=True)
class ClassDefinition:
    name: str
    title: str
    description: str
    stats: dict[str, StatDefinition]
    source_path: Path

    @property
    def stat_values(self) -> dict[str, int]:
        """Just the numeric values, for consumers that don't care about effects.

        Keeps `class_stats` a plain dict[str, int] all the way through
        CardDefinition and CardStore, so v0.2's persisted stat data needs no
        migration when v0.4 adds effect metadata to the class definitions.
        """
        return {name: definition.value for name, definition in self.stats.items()}
