"""DefinitionLoader — reads Agent_Definition YAML files into AgentDefinition instances."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

import yaml

from agent_kit.card_loader import parse_card
from agent_kit.definition import AgentDefinition
from agent_kit.errors import (
    AgentKitError,
    LoadSummaryError,
    MissingFieldError,
    TemperatureRangeError,
    UnresolvableOutputModelError,
    YAMLSyntaxError,
)

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = ("name", "system_prompt", "output_model")
_DEFAULT_MODEL = "qwen2.5:14b"
_DEFAULT_TEMPERATURE = 0.7


class DefinitionLoader:
    def load_file(self, path: Path) -> AgentDefinition:
        raw_text = path.read_text()
        try:
            data = yaml.safe_load(raw_text)
        except yaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            location = f"line {mark.line + 1}, column {mark.column + 1}" if mark else "unknown location"
            raise YAMLSyntaxError(str(path), location) from e

        data = data or {}

        for required in _REQUIRED_FIELDS:
            if required not in data or data[required] is None:
                raise MissingFieldError(f"missing required field '{required}' in {path}")

        temperature = data.get("temperature", _DEFAULT_TEMPERATURE)
        if not (0.0 <= float(temperature) <= 2.0):
            raise TemperatureRangeError(
                f"temperature {temperature!r} in {path} is outside the allowed range [0.0, 2.0]"
            )

        output_model_ref = data["output_model"]
        try:
            module_name, class_name = output_model_ref.rsplit(".", 1)
            module = importlib.import_module(module_name)
            output_model = getattr(module, class_name)
        except Exception as e:
            raise UnresolvableOutputModelError(
                f"cannot resolve output_model '{output_model_ref}' referenced in {path}: {e}"
            ) from e

        card_data = data.get("card")
        card = parse_card(card_data, path) if card_data is not None else None

        return AgentDefinition(
            name=data["name"],
            description=data.get("description", ""),
            system_prompt=data["system_prompt"],
            model=data.get("model", _DEFAULT_MODEL),
            temperature=float(temperature),
            tools=list(data.get("tools", [])),
            output_model=output_model,
            source_path=path,
            feeds=list(data.get("feeds", [])),
            card=card,
        )

    def load_directory(self, directory: Path) -> list[AgentDefinition]:
        definitions: list[AgentDefinition] = []
        errors: list[AgentKitError] = []

        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix not in (".yaml", ".yml"):
                continue
            try:
                definitions.append(self.load_file(path))
            except AgentKitError as e:
                errors.append(e)

        if errors:
            for e in errors:
                logger.warning("failed to load agent definition: %s", e)

        if errors and not definitions:
            summary = "; ".join(str(e) for e in errors)
            err = LoadSummaryError(
                f"failed to load any agent definitions from {directory}: {summary}"
            )
            err.errors = errors
            raise err

        return definitions
