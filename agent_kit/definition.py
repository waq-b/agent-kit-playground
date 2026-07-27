"""AgentDefinition — the parsed, immutable content of one YAML agent file."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str
    system_prompt: str
    model: str
    temperature: float
    tools: list[str]
    output_model: type[BaseModel]
    source_path: Path
    feeds: list[str] = field(default_factory=list)
