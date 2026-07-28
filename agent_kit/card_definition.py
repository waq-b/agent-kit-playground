"""CardDefinition — one agent's resolved character-sheet template."""

from __future__ import annotations

from dataclasses import dataclass

from agent_kit.class_definition import ClassDefinition


@dataclass(frozen=True)
class UnlockEntry:
    level: int
    unlock: str
    description: str = ""


@dataclass(frozen=True)
class CardDefinition:
    title: str
    backstory: str
    portrait: str
    main_class: ClassDefinition
    sub_class: ClassDefinition | None
    class_stats: dict[str, int]
    base_stats: dict[str, int]
    unlock_table: tuple[UnlockEntry, ...]
    starting_level: int
    starting_xp: int
