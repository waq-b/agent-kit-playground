"""AgentDefinition — the parsed, immutable content of one YAML agent file."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from agent_kit.card_definition import CardDefinition


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
    card: CardDefinition | None = None
    # Optional, unlike output_model: an agent with no declared input contract
    # still runs exactly as it always has (POST /run passes the body through
    # unvalidated). Mirrors output_model in every other respect — same dotted
    # path resolution, same error type on an unresolvable reference.
    input_model: type[BaseModel] | None = None
