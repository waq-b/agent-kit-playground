import pytest

from agent_kit.class_loader import ClassLoader
from agent_kit.errors import (
    MissingFieldError,
    ReservedStatNameError,
    StatRangeError,
    YAMLSyntaxError,
)


def test_loads_yaml_and_yml_files(tmp_path):
    (tmp_path / "a.yaml").write_text("name: a\ntitle: A\nstats:\n  warmth: 50\n")
    (tmp_path / "b.yml").write_text("name: b\ntitle: B\nstats:\n  wit: 40\n")

    defs = ClassLoader().load_directory(tmp_path)
    assert sorted(d.name for d in defs) == ["a", "b"]


def test_non_yaml_files_are_silently_skipped(tmp_path):
    (tmp_path / "a.yaml").write_text("name: a\ntitle: A\nstats:\n  warmth: 50\n")
    (tmp_path / "notes.txt").write_text("name: not_a_class\n")

    defs = ClassLoader().load_directory(tmp_path)
    assert [d.name for d in defs] == ["a"]


def test_missing_required_field_raises_missing_field_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: bad\nstats:\n  warmth: 50\n")  # missing title

    with pytest.raises(MissingFieldError):
        ClassLoader().load_file(path)


def test_missing_stats_raises_missing_field_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: bad\ntitle: Bad\nstats: {}\n")  # empty stats

    with pytest.raises(MissingFieldError):
        ClassLoader().load_file(path)


def test_bad_yaml_syntax_raises_yaml_syntax_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: [unterminated\ntitle: \"hi\n")

    with pytest.raises(YAMLSyntaxError):
        ClassLoader().load_file(path)


def test_stat_out_of_range_raises_stat_range_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: bad\ntitle: Bad\nstats:\n  warmth: 150\n")

    with pytest.raises(StatRangeError):
        ClassLoader().load_file(path)


def test_reserved_stat_name_raises_reserved_stat_name_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: bad\ntitle: Bad\nstats:\n  accuracy: 50\n")

    with pytest.raises(ReservedStatNameError):
        ClassLoader().load_file(path)


def test_directory_with_one_bad_file_and_n_good_files_returns_n(tmp_path):
    for i in range(3):
        (tmp_path / f"good{i}.yaml").write_text(f"name: good{i}\ntitle: Good{i}\nstats:\n  warmth: 50\n")
    (tmp_path / "bad.yaml").write_text("name: bad\n")  # missing title/stats

    defs = ClassLoader().load_directory(tmp_path)
    assert len(defs) == 3
    assert sorted(d.name for d in defs) == ["good0", "good1", "good2"]
