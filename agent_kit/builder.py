"""builder.py — Agent Builder core: create/edit/delete/duplicate agents and classes.

Agents remain data (YAML) under the hood; this module is a friendly face on
the same file format, not a new storage mechanism. It touches zero core
Runner/loader logic — the only core-file changes anywhere in v0.3 are three
small, additive registry methods (replace/remove — see registry.py /
class_registry.py), which don't alter register()/get()'s existing contracts.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

import agent_kit
from agent_kit.card_definition import CardDefinition
from agent_kit.class_loader import ClassLoader
from agent_kit.class_registry import get_class_registry
from agent_kit.definition import AgentDefinition
from agent_kit.errors import (
    AgentKitError,
    AgentNotFoundError,
    ClassNotFoundError,
    CoreAgentConfirmationRequiredError,
    DuplicateAgentError,
    DuplicateClassError,
    OutputModelNotEditableError,
)
from agent_kit.loader import DefinitionLoader
from agent_kit.model_codegen import FieldSpec, generate_model_source, output_class_name
from agent_kit.registry import get_registry
from agent_kit.settings import resolve_model_provider
from agent_kit.stub_store import get_stub_store
from agent_kit.tool_registry import get_tool_registry
from agent_kit.yaml_io import write_yaml_file

_DEFAULT_DATA_DIR = "agent_kit_data"
_GENERATED_MODELS_PACKAGE = "agent_kit_generated_models"

CORE_AGENT_NAMES = frozenset({"hello", "news"})


@dataclass(frozen=True)
class BuilderPaths:
    data_dir: Path

    @property
    def agents_dir(self) -> Path:
        return self.data_dir / "agents"

    @property
    def classes_dir(self) -> Path:
        return self.data_dir / "classes"

    @property
    def generated_models_dir(self) -> Path:
        return self.data_dir / _GENERATED_MODELS_PACKAGE

    @property
    def generated_models_package(self) -> str:
        return _GENERATED_MODELS_PACKAGE

    @property
    def deleted_agents_file(self) -> Path:
        return self.data_dir / "deleted_agents.json"

    def sample_input_file(self, agent_name: str) -> Path:
        return self.data_dir / f"{agent_name}.sample.json"


def default_builder_paths() -> BuilderPaths:
    root = os.environ.get("AGENT_KIT_DATA_DIR", _DEFAULT_DATA_DIR)
    return BuilderPaths(data_dir=Path(root))


DEFAULT_PATHS = default_builder_paths()


def ensure_data_dirs(paths: BuilderPaths | None = None) -> None:
    paths = paths or DEFAULT_PATHS
    paths.agents_dir.mkdir(parents=True, exist_ok=True)
    paths.classes_dir.mkdir(parents=True, exist_ok=True)
    paths.generated_models_dir.mkdir(parents=True, exist_ok=True)

    init_file = paths.generated_models_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text("")

    data_dir_str = str(paths.data_dir.resolve())
    if data_dir_str not in sys.path:
        sys.path.insert(0, data_dir_str)


def is_builder_generated(definition: AgentDefinition, paths: BuilderPaths | None = None) -> bool:
    paths = paths or DEFAULT_PATHS
    module = getattr(definition.output_model, "__module__", "")
    prefix = paths.generated_models_package
    return module == prefix or module.startswith(prefix + ".")


def _invalidate_generated_model_modules(paths: BuilderPaths | None = None) -> None:
    paths = paths or DEFAULT_PATHS
    prefix = paths.generated_models_package
    for name in [n for n in sys.modules if n == prefix or n.startswith(prefix + ".")]:
        del sys.modules[name]
    importlib.invalidate_caches()


def _read_deleted_agents(paths: BuilderPaths) -> set[str]:
    if not paths.deleted_agents_file.exists():
        return set()
    return set(json.loads(paths.deleted_agents_file.read_text()))


def _write_deleted_agents(names: set[str], paths: BuilderPaths) -> None:
    paths.deleted_agents_file.write_text(json.dumps(sorted(names)))


def reload_registries(paths: BuilderPaths | None = None) -> None:
    paths = paths or DEFAULT_PATHS
    ensure_data_dirs(paths)
    _invalidate_generated_model_modules(paths)

    get_registry().clear()
    get_class_registry().clear()
    get_stub_store().clear()
    get_tool_registry().clear()

    agent_kit._initialise()  # pristine built-ins first

    for class_def in ClassLoader().load_directory(paths.classes_dir):
        get_class_registry().replace(class_def)

    for agent_def in DefinitionLoader().load_directory(paths.agents_dir):
        get_registry().replace(agent_def)

    for name in _read_deleted_agents(paths):
        get_registry().remove(name)


def _dotted_path(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def card_definition_to_dict(card: CardDefinition | None) -> dict[str, Any] | None:
    if card is None:
        return None
    result: dict[str, Any] = {
        "main_class": card.main_class.name,
        "title": card.title,
        "backstory": card.backstory,
        "portrait": card.portrait,
        "base_stats": dict(card.base_stats),
        "level": card.starting_level,
        "xp": card.starting_xp,
    }
    if card.sub_class:
        result["sub_class"] = card.sub_class.name
    if card.unlock_table:
        result["unlock_table"] = [
            {"level": u.level, "unlock": u.unlock, "description": u.description}
            for u in card.unlock_table
        ]
    return result


def _write_generated_model(
    name: str, output_fields: list[FieldSpec], paths: BuilderPaths
) -> tuple[Path, bytes | None]:
    """Renders + writes the generated model file, returning (path, previous_bytes)
    so a failed commit can restore the prior state (or delete, for a fresh create)."""
    source = generate_model_source(name, output_fields)  # raises before any write
    model_path = paths.generated_models_dir / f"{name}.py"
    previous_bytes = model_path.read_bytes() if model_path.exists() else None
    model_path.write_text(source)
    _invalidate_generated_model_modules(paths)
    return model_path, previous_bytes


def _restore_generated_model(model_path: Path, previous_bytes: bytes | None, paths: BuilderPaths) -> None:
    if previous_bytes is None:
        model_path.unlink(missing_ok=True)
    else:
        model_path.write_bytes(previous_bytes)
    _invalidate_generated_model_modules(paths)


def _commit_agent_yaml(name: str, data: dict[str, Any], paths: BuilderPaths) -> AgentDefinition:
    """Validate-then-commit: write to a tmp file, validate with the real
    DefinitionLoader against real bytes on disk, only then promote atomically."""
    final_path = paths.agents_dir / f"{name}.yaml"
    tmp_path = paths.agents_dir / f"{name}.yaml.tmp"
    write_yaml_file(tmp_path, data)
    try:
        DefinitionLoader().load_file(tmp_path)
    except AgentKitError:
        tmp_path.unlink(missing_ok=True)
        raise
    os.replace(tmp_path, final_path)
    reload_registries(paths)
    return get_registry().get(name)


def create_agent(
    name: str,
    *,
    system_prompt: str,
    output_fields: list[FieldSpec],
    description: str = "",
    model: str = "qwen2.5:14b",
    temperature: float = 0.7,
    tools: list[str] | None = None,
    feeds: list[str] | None = None,
    card: dict[str, Any] | None = None,
    sample_input: dict[str, Any] | None = None,
    paths: BuilderPaths | None = None,
) -> AgentDefinition:
    paths = paths or DEFAULT_PATHS
    ensure_data_dirs(paths)

    try:
        get_registry().get(name)
    except AgentNotFoundError:
        pass
    else:
        raise DuplicateAgentError(f"agent '{name}' is already registered")

    # Un-tombstone *before* committing: _commit_agent_yaml triggers a reload,
    # which re-applies tombstones — a stale one would immediately remove the
    # agent we're about to create.
    deleted = _read_deleted_agents(paths)
    if name in deleted:
        deleted.discard(name)
        _write_deleted_agents(deleted, paths)

    model_path, previous_bytes = _write_generated_model(name, output_fields, paths)

    output_model_ref = f"{paths.generated_models_package}.{name}.{output_class_name(name)}"
    data: dict[str, Any] = {
        "name": name,
        "description": description,
        "system_prompt": system_prompt,
        "model": model,
        "temperature": temperature,
        "tools": list(tools or []),
        "output_model": output_model_ref,
    }
    if feeds:
        data["feeds"] = list(feeds)
    if card:
        data["card"] = card

    try:
        result = _commit_agent_yaml(name, data, paths)
    except AgentKitError:
        _restore_generated_model(model_path, previous_bytes, paths)
        raise

    if sample_input is not None:
        write_sample_input(name, sample_input, paths)

    return result


def update_agent(
    name: str,
    *,
    system_prompt: str | None = None,
    output_fields: list[FieldSpec] | None = None,
    description: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    tools: list[str] | None = None,
    feeds: list[str] | None = None,
    card: dict[str, Any] | None = None,
    sample_input: dict[str, Any] | None = None,
    paths: BuilderPaths | None = None,
) -> AgentDefinition:
    paths = paths or DEFAULT_PATHS
    ensure_data_dirs(paths)

    current = get_registry().get(name)  # raises AgentNotFoundError if unknown

    if output_fields is not None and not is_builder_generated(current, paths):
        raise OutputModelNotEditableError(
            f"agent '{name}'s output schema is hand-written and cannot be edited through the builder"
        )

    data: dict[str, Any] = {
        "name": name,
        "description": description if description is not None else current.description,
        "system_prompt": system_prompt if system_prompt is not None else current.system_prompt,
        "model": model if model is not None else current.model,
        "temperature": temperature if temperature is not None else current.temperature,
        "tools": list(tools) if tools is not None else list(current.tools),
    }

    effective_feeds = feeds if feeds is not None else list(current.feeds)
    if effective_feeds:
        data["feeds"] = effective_feeds

    effective_card = card if card is not None else card_definition_to_dict(current.card)
    if effective_card:
        data["card"] = effective_card

    model_path: Path | None = None
    previous_bytes: bytes | None = None
    if output_fields is not None:
        model_path, previous_bytes = _write_generated_model(name, output_fields, paths)
        data["output_model"] = f"{paths.generated_models_package}.{name}.{output_class_name(name)}"
    else:
        data["output_model"] = _dotted_path(current.output_model)

    try:
        result = _commit_agent_yaml(name, data, paths)
    except AgentKitError:
        if model_path is not None:
            _restore_generated_model(model_path, previous_bytes, paths)
        raise

    if sample_input is not None:
        write_sample_input(name, sample_input, paths)

    return result


def delete_agent(name: str, confirm_core: bool = False, paths: BuilderPaths | None = None) -> None:
    paths = paths or DEFAULT_PATHS
    ensure_data_dirs(paths)
    definition = get_registry().get(name)  # raises AgentNotFoundError if unknown

    if name in CORE_AGENT_NAMES and not confirm_core:
        raise CoreAgentConfirmationRequiredError(
            f"deleting core demo agent '{name}' requires confirm_core=True"
        )

    (paths.agents_dir / f"{name}.yaml").unlink(missing_ok=True)

    if is_builder_generated(definition, paths):
        (paths.generated_models_dir / f"{name}.py").unlink(missing_ok=True)
        _invalidate_generated_model_modules(paths)

    delete_sample_input(name, paths)

    deleted = _read_deleted_agents(paths)
    deleted.add(name)
    _write_deleted_agents(deleted, paths)

    reload_registries(paths)


def duplicate_agent(name: str, new_name: str, paths: BuilderPaths | None = None) -> AgentDefinition:
    paths = paths or DEFAULT_PATHS
    ensure_data_dirs(paths)

    current = get_registry().get(name)  # raises AgentNotFoundError if unknown

    try:
        get_registry().get(new_name)
    except AgentNotFoundError:
        pass
    else:
        raise DuplicateAgentError(f"agent '{new_name}' is already registered")

    data: dict[str, Any] = {
        "name": new_name,
        "description": current.description,
        "system_prompt": current.system_prompt,
        "model": current.model,
        "temperature": current.temperature,
        "tools": list(current.tools),
    }
    if current.feeds:
        data["feeds"] = list(current.feeds)
    card_dict = card_definition_to_dict(current.card)
    if card_dict:
        data["card"] = card_dict

    if is_builder_generated(current, paths):
        source = (paths.generated_models_dir / f"{name}.py").read_text()
        new_model_path = paths.generated_models_dir / f"{new_name}.py"
        new_model_path.write_text(source.replace(current.output_model.__name__, f"{output_class_name(new_name)}"))
        _invalidate_generated_model_modules(paths)
        data["output_model"] = f"{paths.generated_models_package}.{new_name}.{output_class_name(new_name)}"
    else:
        # Hand-written model classes are safe to share — no file duplication needed.
        data["output_model"] = _dotted_path(current.output_model)

    return _commit_agent_yaml(new_name, data, paths)


def create_class(content: str, paths: BuilderPaths | None = None) -> Any:
    """Create a class from raw YAML or JSON source text (JSON parses fine as
    YAML, so no separate JSON path is needed). Classes are authored directly
    as code, not through form pickers — this validates with the real
    ClassLoader against real bytes on disk (same validate-then-commit pattern
    as agents), then re-serializes the parsed content through yaml_io for
    canonical formatting before the final write.
    """
    paths = paths or DEFAULT_PATHS
    ensure_data_dirs(paths)

    tmp_path = paths.classes_dir / f".tmp-{uuid.uuid4().hex}.yaml"
    tmp_path.write_text(content)
    try:
        class_def = ClassLoader().load_file(tmp_path)
    except AgentKitError:
        tmp_path.unlink(missing_ok=True)
        raise

    try:
        get_class_registry().get(class_def.name)
    except ClassNotFoundError:
        pass
    else:
        tmp_path.unlink(missing_ok=True)
        raise DuplicateClassError(f"class '{class_def.name}' is already registered")

    parsed = yaml.safe_load(content)
    final_path = paths.classes_dir / f"{class_def.name}.yaml"
    write_yaml_file(final_path, parsed)
    tmp_path.unlink(missing_ok=True)

    reload_registries(paths)
    return get_class_registry().get(class_def.name)


def check_model_reachable(model_name: str) -> dict[str, Any]:
    """Soft, best-effort check — never raises, never blocks save, works offline."""
    resolved = resolve_model_provider(model_name)
    headers = {"Authorization": f"Bearer {resolved.api_key}"} if resolved.is_frontier else None
    source = "the registered frontier provider" if resolved.is_frontier else "local Ollama"
    try:
        response = httpx.get(f"{resolved.base_url}/models", headers=headers, timeout=2.0)
        response.raise_for_status()
        available_models = {m["id"] for m in response.json().get("data", [])}
        if model_name in available_models:
            return {"available": True, "message": f"'{model_name}' found on {source}"}
        return {"available": False, "message": f"'{model_name}' not found in {source}'s model list"}
    except Exception as e:
        return {"available": False, "message": f"could not reach {source} to check: {e}"}


def read_sample_input(name: str, paths: BuilderPaths | None = None) -> dict[str, Any] | None:
    paths = paths or DEFAULT_PATHS
    path = paths.sample_input_file(name)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def write_sample_input(name: str, sample: dict[str, Any], paths: BuilderPaths | None = None) -> None:
    paths = paths or DEFAULT_PATHS
    ensure_data_dirs(paths)
    paths.sample_input_file(name).write_text(json.dumps(sample))


def delete_sample_input(name: str, paths: BuilderPaths | None = None) -> None:
    paths = paths or DEFAULT_PATHS
    paths.sample_input_file(name).unlink(missing_ok=True)


# Sample input is normally something a user fills in through the Builder wizard
# when they create an agent — but hello/news ship as plain YAML in agent_kit/,
# never went through the wizard, and so never got one. Without it the Run
# screen has nothing to prefill and no way to derive the Roster's "Input"
# column, even though the real input shape is well known (see
# agent_kit/agents/models/{hello,news}.py). Seeded once at startup via the
# exact same read/write path a wizard-filled sample uses, so nothing else has
# to treat "core" and "user-created" agents differently.
_CORE_SAMPLE_INPUTS: dict[str, dict[str, Any]] = {
    "hello": {"name": "Alice"},
    "news": {"keywords": ["AI", "climate"]},
}


def seed_core_sample_inputs(paths: BuilderPaths | None = None) -> None:
    """Fill in a sample input for any core agent that doesn't already have one.

    Never overwrites — if a user has since edited it via the wizard, that edit
    wins. Silently does nothing for a core agent name not in the map, so
    adding a new core agent without a seeded example is a no-op, not an error.
    """
    for name, sample in _CORE_SAMPLE_INPUTS.items():
        if read_sample_input(name, paths) is None:
            write_sample_input(name, sample, paths)
