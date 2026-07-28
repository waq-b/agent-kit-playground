"""ClassLoader — reads class-template YAML files into ClassDefinition instances."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from agent_kit.class_definition import BASE_STAT_NAMES, ClassDefinition
from agent_kit.errors import (
    AgentKitError,
    LoadSummaryError,
    MissingFieldError,
    ReservedStatNameError,
    StatRangeError,
    YAMLSyntaxError,
)

logger = logging.getLogger(__name__)

_REQUIRED_CLASS_FIELDS = ("name", "title", "stats")


class ClassLoader:
    def load_file(self, path: Path) -> ClassDefinition:
        raw_text = path.read_text()
        try:
            data = yaml.safe_load(raw_text)
        except yaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            location = f"line {mark.line + 1}, column {mark.column + 1}" if mark else "unknown location"
            raise YAMLSyntaxError(str(path), location) from e

        data = data or {}

        for required in _REQUIRED_CLASS_FIELDS:
            if required not in data or data[required] is None:
                raise MissingFieldError(f"missing required field '{required}' in {path}")

        stats = data["stats"]
        if not isinstance(stats, dict) or not stats:
            raise MissingFieldError(f"'stats' must be a non-empty mapping in {path}")

        reserved = set(stats) & set(BASE_STAT_NAMES)
        if reserved:
            raise ReservedStatNameError(
                f"class stats in {path} use reserved base-stat name(s) {sorted(reserved)}"
            )

        for stat_name, value in stats.items():
            if not (0 <= value <= 100):
                raise StatRangeError(
                    f"class stat '{stat_name}' = {value!r} in {path} is outside the allowed range [0, 100]"
                )

        return ClassDefinition(
            name=data["name"],
            title=data["title"],
            description=data.get("description", ""),
            stats={k: int(v) for k, v in stats.items()},
            source_path=path,
        )

    def load_directory(self, directory: Path) -> list[ClassDefinition]:
        definitions: list[ClassDefinition] = []
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
                logger.warning("failed to load class definition: %s", e)

        if errors and not definitions:
            summary = "; ".join(str(e) for e in errors)
            err = LoadSummaryError(
                f"failed to load any class definitions from {directory}: {summary}"
            )
            err.errors = errors
            raise err

        return definitions
