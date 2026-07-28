"""ClassLoader — reads class-template YAML files into ClassDefinition instances."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from agent_kit.class_definition import BASE_STAT_NAMES, ClassDefinition
from agent_kit.errors import (
    AgentKitError,
    InvalidStatEffectError,
    LoadSummaryError,
    MissingFieldError,
    MissingPromptEffectError,
    MissingRuntimeEffectError,
    ReservedStatNameError,
    StatRangeError,
    UnknownRuntimeParameterError,
    YAMLSyntaxError,
)
from agent_kit.stat_effects import (
    RUNTIME_PARAMETER_BOUNDS,
    PromptBand,
    RuntimeCurve,
    StatDefinition,
)

logger = logging.getLogger(__name__)

_REQUIRED_CLASS_FIELDS = ("name", "title", "stats")


def _parse_stat(stat_name: str, raw: object, path: Path) -> StatDefinition:
    """Parse one stat's `{value, prompt_effect, runtime_effect}` object.

    The pre-v0.4 flat form (`stat_name: 65`) is rejected outright rather than
    defaulted: a stat with no authored effects would silently do nothing at
    run time, which is exactly the failure mode the effects engine exists to
    eliminate.
    """
    if not isinstance(raw, dict):
        raise InvalidStatEffectError(
            f"class stat '{stat_name}' in {path} must be a mapping with 'value', "
            f"'prompt_effect' and 'runtime_effect' keys (got {type(raw).__name__}). "
            "The pre-v0.4 flat 'name: value' form is no longer supported."
        )

    if "value" not in raw or raw["value"] is None:
        raise InvalidStatEffectError(f"class stat '{stat_name}' in {path} is missing 'value'")
    value = raw["value"]
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not (0 <= value <= 100):
        raise StatRangeError(
            f"class stat '{stat_name}' = {value!r} in {path} is outside the allowed range [0, 100]"
        )

    raw_bands = raw.get("prompt_effect")
    if not raw_bands:
        raise MissingPromptEffectError(
            f"class stat '{stat_name}' in {path} must define at least one prompt_effect band"
        )
    if not isinstance(raw_bands, list):
        raise InvalidStatEffectError(
            f"class stat '{stat_name}' prompt_effect in {path} must be a list of bands"
        )

    bands: list[PromptBand] = []
    for band in raw_bands:
        if not isinstance(band, dict) or "label" not in band or "text" not in band:
            raise InvalidStatEffectError(
                f"class stat '{stat_name}' in {path} has a prompt_effect band missing 'label' or 'text'"
            )
        bands.append(PromptBand(label=str(band["label"]), text=str(band["text"])))

    raw_runtime = raw.get("runtime_effect")
    if not raw_runtime:
        raise MissingRuntimeEffectError(
            f"class stat '{stat_name}' in {path} must define a runtime_effect"
        )
    if not isinstance(raw_runtime, dict):
        raise InvalidStatEffectError(
            f"class stat '{stat_name}' runtime_effect in {path} must be a mapping of parameter to curve"
        )

    curves: dict[str, RuntimeCurve] = {}
    for parameter, curve in raw_runtime.items():
        if parameter not in RUNTIME_PARAMETER_BOUNDS:
            raise UnknownRuntimeParameterError(
                f"class stat '{stat_name}' in {path} targets unknown runtime parameter "
                f"'{parameter}'; valid parameters are {sorted(RUNTIME_PARAMETER_BOUNDS)}"
            )
        if not isinstance(curve, dict) or "at_0" not in curve or "at_100" not in curve:
            raise InvalidStatEffectError(
                f"class stat '{stat_name}' runtime_effect '{parameter}' in {path} "
                "must be a mapping with 'at_0' and 'at_100'"
            )
        curves[parameter] = RuntimeCurve(at_0=float(curve["at_0"]), at_100=float(curve["at_100"]))

    return StatDefinition(value=int(value), prompt_effect=tuple(bands), runtime_effect=curves)


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

        return ClassDefinition(
            name=data["name"],
            title=data["title"],
            description=data.get("description", ""),
            stats={name: _parse_stat(name, raw, path) for name, raw in stats.items()},
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
