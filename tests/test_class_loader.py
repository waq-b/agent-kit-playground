import pytest

from agent_kit.class_loader import ClassLoader
from agent_kit.errors import (
    InvalidStatEffectError,
    MissingFieldError,
    MissingPromptEffectError,
    MissingRuntimeEffectError,
    ReservedStatNameError,
    StatRangeError,
    UnknownRuntimeParameterError,
    YAMLSyntaxError,
)
from tests.conftest import stat_yaml


def class_yaml(name: str, title: str, stat_name: str = "warmth", value: int = 50) -> str:
    return f"name: {name}\ntitle: {title}\nstats:\n" + stat_yaml(stat_name, value)


def test_loads_yaml_and_yml_files(tmp_path):
    (tmp_path / "a.yaml").write_text(class_yaml("a", "A"))
    (tmp_path / "b.yml").write_text(class_yaml("b", "B", "wit", 40))

    defs = ClassLoader().load_directory(tmp_path)
    assert sorted(d.name for d in defs) == ["a", "b"]


def test_non_yaml_files_are_silently_skipped(tmp_path):
    (tmp_path / "a.yaml").write_text(class_yaml("a", "A"))
    (tmp_path / "notes.txt").write_text("name: not_a_class\n")

    defs = ClassLoader().load_directory(tmp_path)
    assert [d.name for d in defs] == ["a"]


def test_parses_stat_effects(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text(class_yaml("a", "A", "warmth", 80))

    definition = ClassLoader().load_file(path)
    stat = definition.stats["warmth"]
    assert stat.value == 80
    assert [band.label for band in stat.prompt_effect] == ["low", "high"]
    assert stat.runtime_effect["temperature"].at_100 == 0.1


def test_stat_values_property_returns_plain_ints(tmp_path):
    """CardDefinition/CardStore still carry dict[str, int]; this is the bridge."""
    path = tmp_path / "a.yaml"
    path.write_text(class_yaml("a", "A", "warmth", 80))

    assert ClassLoader().load_file(path).stat_values == {"warmth": 80}


def test_missing_required_field_raises_missing_field_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: bad\nstats:\n" + stat_yaml("warmth", 50))  # missing title

    with pytest.raises(MissingFieldError):
        ClassLoader().load_file(path)


def test_missing_stats_raises_missing_field_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: bad\ntitle: Bad\nstats: {}\n")

    with pytest.raises(MissingFieldError):
        ClassLoader().load_file(path)


def test_bad_yaml_syntax_raises_yaml_syntax_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: [unterminated\ntitle: \"hi\n")

    with pytest.raises(YAMLSyntaxError):
        ClassLoader().load_file(path)


def test_legacy_flat_stat_form_is_rejected(tmp_path):
    """The pre-v0.4 `stat_name: 65` form must fail loudly, not silently default
    to a stat with no effects."""
    path = tmp_path / "bad.yaml"
    path.write_text("name: bad\ntitle: Bad\nstats:\n  warmth: 50\n")

    with pytest.raises(InvalidStatEffectError):
        ClassLoader().load_file(path)


def test_stat_out_of_range_raises_stat_range_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: bad\ntitle: Bad\nstats:\n" + stat_yaml("warmth", 150))

    with pytest.raises(StatRangeError):
        ClassLoader().load_file(path)


def test_stat_missing_value_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "name: bad\ntitle: Bad\nstats:\n  warmth:\n    prompt_effect:\n"
        "      - label: low\n        text: t\n    runtime_effect:\n      temperature: {at_0: 0, at_100: 1}\n"
    )

    with pytest.raises(InvalidStatEffectError):
        ClassLoader().load_file(path)


def test_stat_missing_prompt_effect_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "name: bad\ntitle: Bad\nstats:\n  warmth:\n    value: 50\n"
        "    runtime_effect:\n      temperature: {at_0: 0, at_100: 1}\n"
    )

    with pytest.raises(MissingPromptEffectError):
        ClassLoader().load_file(path)


def test_stat_empty_prompt_effect_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "name: bad\ntitle: Bad\nstats:\n  warmth:\n    value: 50\n    prompt_effect: []\n"
        "    runtime_effect:\n      temperature: {at_0: 0, at_100: 1}\n"
    )

    with pytest.raises(MissingPromptEffectError):
        ClassLoader().load_file(path)


def test_stat_band_missing_label_or_text_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "name: bad\ntitle: Bad\nstats:\n  warmth:\n    value: 50\n"
        "    prompt_effect:\n      - label: low\n"
        "    runtime_effect:\n      temperature: {at_0: 0, at_100: 1}\n"
    )

    with pytest.raises(InvalidStatEffectError):
        ClassLoader().load_file(path)


def test_stat_missing_runtime_effect_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "name: bad\ntitle: Bad\nstats:\n  warmth:\n    value: 50\n"
        "    prompt_effect:\n      - label: low\n        text: t\n"
    )

    with pytest.raises(MissingRuntimeEffectError):
        ClassLoader().load_file(path)


def test_unknown_runtime_parameter_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "name: bad\ntitle: Bad\nstats:\n  warmth:\n    value: 50\n"
        "    prompt_effect:\n      - label: low\n        text: t\n"
        "    runtime_effect:\n      not_a_real_param: {at_0: 0, at_100: 1}\n"
    )

    with pytest.raises(UnknownRuntimeParameterError):
        ClassLoader().load_file(path)


def test_runtime_curve_missing_endpoint_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "name: bad\ntitle: Bad\nstats:\n  warmth:\n    value: 50\n"
        "    prompt_effect:\n      - label: low\n        text: t\n"
        "    runtime_effect:\n      temperature: {at_0: 0}\n"
    )

    with pytest.raises(InvalidStatEffectError):
        ClassLoader().load_file(path)


def test_reserved_stat_name_raises_reserved_stat_name_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: bad\ntitle: Bad\nstats:\n" + stat_yaml("accuracy", 50))

    with pytest.raises(ReservedStatNameError):
        ClassLoader().load_file(path)


def test_directory_with_one_bad_file_and_n_good_files_returns_n(tmp_path):
    for i in range(3):
        (tmp_path / f"good{i}.yaml").write_text(class_yaml(f"good{i}", f"Good{i}"))
    (tmp_path / "bad.yaml").write_text("name: bad\n")  # missing title/stats

    defs = ClassLoader().load_directory(tmp_path)
    assert len(defs) == 3
    assert sorted(d.name for d in defs) == ["good0", "good1", "good2"]
