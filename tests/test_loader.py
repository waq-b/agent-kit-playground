from pathlib import Path

import pytest

from agent_kit.class_definition import ClassDefinition
from tests.conftest import make_stat
from agent_kit.class_registry import get_class_registry
from agent_kit.errors import (
    ClassNotFoundError,
    MissingFieldError,
    TemperatureRangeError,
    UnresolvableInputModelError,
    UnresolvableOutputModelError,
    YAMLSyntaxError,
)
from agent_kit.loader import DefinitionLoader

# A real, always-importable output_model reference for test fixtures.
OUTPUT_MODEL = "agent_kit.agents.models.hello.HelloOutput"
# A real, always-importable input_model reference for test fixtures.
INPUT_MODEL = "agent_kit.agents.models.hello.HelloInput"


def test_loads_yaml_and_yml_files(tmp_path):
    (tmp_path / "a.yaml").write_text(f"name: a\nsystem_prompt: sp\noutput_model: {OUTPUT_MODEL}\n")
    (tmp_path / "b.yml").write_text(f"name: b\nsystem_prompt: sp\noutput_model: {OUTPUT_MODEL}\n")

    defs = DefinitionLoader().load_directory(tmp_path)
    assert sorted(d.name for d in defs) == ["a", "b"]


def test_non_yaml_files_are_silently_skipped(tmp_path):
    (tmp_path / "a.yaml").write_text(f"name: a\nsystem_prompt: sp\noutput_model: {OUTPUT_MODEL}\n")
    (tmp_path / "notes.txt").write_text("name: not_an_agent\n")

    defs = DefinitionLoader().load_directory(tmp_path)
    assert [d.name for d in defs] == ["a"]


def test_missing_required_field_raises_missing_field_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(f"name: bad\noutput_model: {OUTPUT_MODEL}\n")  # missing system_prompt

    with pytest.raises(MissingFieldError):
        DefinitionLoader().load_file(path)


def test_bad_yaml_syntax_raises_yaml_syntax_error_not_missing_field(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: [unterminated\nsystem_prompt: \"hi\n")

    with pytest.raises(YAMLSyntaxError):
        DefinitionLoader().load_file(path)


def test_bad_yaml_syntax_in_directory_continues_loading_others(tmp_path):
    (tmp_path / "bad.yaml").write_text("name: [unterminated\nsystem_prompt: \"hi\n")
    (tmp_path / "good.yaml").write_text(f"name: good\nsystem_prompt: sp\noutput_model: {OUTPUT_MODEL}\n")

    defs = DefinitionLoader().load_directory(tmp_path)
    assert [d.name for d in defs] == ["good"]


def test_unresolvable_output_model_raises_and_directory_continues(tmp_path):
    (tmp_path / "bad.yaml").write_text("name: bad\nsystem_prompt: sp\noutput_model: nonexistent.module.Out\n")
    (tmp_path / "good.yaml").write_text(f"name: good\nsystem_prompt: sp\noutput_model: {OUTPUT_MODEL}\n")

    with pytest.raises(UnresolvableOutputModelError):
        DefinitionLoader().load_file(tmp_path / "bad.yaml")

    defs = DefinitionLoader().load_directory(tmp_path)
    assert [d.name for d in defs] == ["good"]


def test_agent_without_input_model_has_none_input_model(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text(f"name: a\nsystem_prompt: sp\noutput_model: {OUTPUT_MODEL}\n")

    definition = DefinitionLoader().load_file(path)
    assert definition.input_model is None


def test_agent_with_input_model_resolves_it(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text(
        f"name: a\nsystem_prompt: sp\noutput_model: {OUTPUT_MODEL}\ninput_model: {INPUT_MODEL}\n"
    )

    definition = DefinitionLoader().load_file(path)
    from agent_kit.agents.models.hello import HelloInput

    assert definition.input_model is HelloInput


def test_unresolvable_input_model_raises_and_directory_continues(tmp_path):
    (tmp_path / "bad.yaml").write_text(
        f"name: bad\nsystem_prompt: sp\noutput_model: {OUTPUT_MODEL}\ninput_model: nonexistent.module.In\n"
    )
    (tmp_path / "good.yaml").write_text(f"name: good\nsystem_prompt: sp\noutput_model: {OUTPUT_MODEL}\n")

    with pytest.raises(UnresolvableInputModelError):
        DefinitionLoader().load_file(tmp_path / "bad.yaml")

    defs = DefinitionLoader().load_directory(tmp_path)
    assert [d.name for d in defs] == ["good"]


def test_invalid_temperature_raises_temperature_range_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(f"name: bad\nsystem_prompt: sp\noutput_model: {OUTPUT_MODEL}\ntemperature: 5.0\n")

    with pytest.raises(TemperatureRangeError):
        DefinitionLoader().load_file(path)


def test_directory_with_one_bad_file_and_n_good_files_returns_n(tmp_path):
    for i in range(3):
        (tmp_path / f"good{i}.yaml").write_text(
            f"name: good{i}\nsystem_prompt: sp\noutput_model: {OUTPUT_MODEL}\n"
        )
    (tmp_path / "bad.yaml").write_text("name: bad\n")  # missing system_prompt + output_model

    defs = DefinitionLoader().load_directory(tmp_path)
    assert len(defs) == 3
    assert sorted(d.name for d in defs) == ["good0", "good1", "good2"]


@pytest.fixture
def _isolated_class_registry():
    get_class_registry().clear()
    get_class_registry().register(
        ClassDefinition(name="greeter", title="Greeter", description="d", stats={"warmth": make_stat(60)}, source_path=Path("test_class.yaml"))
    )
    get_class_registry().register(
        ClassDefinition(name="investigator", title="Investigator", description="d", stats={"skepticism": make_stat(70)}, source_path=Path("test_class.yaml"))
    )
    yield
    get_class_registry().clear()


def test_agent_without_card_section_has_none_card(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text(f"name: a\nsystem_prompt: sp\noutput_model: {OUTPUT_MODEL}\n")

    definition = DefinitionLoader().load_file(path)
    assert definition.card is None


def test_agent_with_main_class_only_card(tmp_path, _isolated_class_registry):
    path = tmp_path / "a.yaml"
    path.write_text(
        f"name: a\nsystem_prompt: sp\noutput_model: {OUTPUT_MODEL}\n"
        "card:\n  main_class: greeter\n"
    )

    definition = DefinitionLoader().load_file(path)
    assert definition.card is not None
    assert definition.card.title == "Greeter"
    assert definition.card.sub_class is None


def test_agent_with_main_and_sub_class_card(tmp_path, _isolated_class_registry):
    path = tmp_path / "a.yaml"
    path.write_text(
        f"name: a\nsystem_prompt: sp\noutput_model: {OUTPUT_MODEL}\n"
        "card:\n  main_class: greeter\n  sub_class: investigator\n"
    )

    definition = DefinitionLoader().load_file(path)
    assert definition.card.title == "Greeter Investigator"
    assert definition.card.class_stats == {"warmth": 60, "skepticism": 70}


def test_agent_card_with_unknown_class_raises_class_not_found_error(tmp_path, _isolated_class_registry):
    path = tmp_path / "a.yaml"
    path.write_text(
        f"name: a\nsystem_prompt: sp\noutput_model: {OUTPUT_MODEL}\n"
        "card:\n  main_class: nonexistent\n"
    )

    with pytest.raises(ClassNotFoundError):
        DefinitionLoader().load_file(path)
