"""ClassDefinition — a reusable, named bundle of class-specific stats."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BASE_STAT_NAMES = ("accuracy", "insight", "speed", "reliability")
DEFAULT_BASE_STAT_VALUE = 50


@dataclass(frozen=True)
class ClassDefinition:
    name: str
    title: str
    description: str
    stats: dict[str, int]
    source_path: Path
