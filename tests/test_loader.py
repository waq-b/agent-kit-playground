import pytest

from agent_kit.errors import (
    MissingFieldError,
    TemperatureRangeError,
    UnresolvableOutputModelError,
    YAMLSyntaxError,
)
from agent_kit.loader import DefinitionLoader

# A real, always-importable output_model reference for test fixtures.
OUTPUT_MODEL = "agent_kit.agents.models.hello.HelloOutput"


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
