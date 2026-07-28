from pathlib import Path

import pytest

from agent_kit.class_definition import ClassDefinition
from agent_kit.class_registry import ClassRegistry
from tests.conftest import make_stat
from agent_kit.errors import ClassNotFoundError, DuplicateClassError


def make(name: str, path: str = "a.yaml") -> ClassDefinition:
    return ClassDefinition(
        name=name, title=name.title(), description="d",
        stats={"warmth": make_stat(50)}, source_path=Path(path),
    )


def test_register_get_list_clear():
    r = ClassRegistry()
    r.register(make("greeter"))
    assert r.get("greeter").name == "greeter"
    assert r.list() == [{"name": "greeter", "title": "Greeter"}]
    r.clear()
    assert r.list() == []


def test_duplicate_class_error_on_second_registration():
    r = ClassRegistry()
    r.register(make("greeter", "a.yaml"))
    with pytest.raises(DuplicateClassError):
        r.register(make("greeter", "b.yaml"))


def test_class_not_found_error_on_unknown_name():
    r = ClassRegistry()
    with pytest.raises(ClassNotFoundError) as exc_info:
        r.get("nope")
    assert "nope" in str(exc_info.value)


def test_list_returns_exactly_name_and_title_per_entry():
    r = ClassRegistry()
    r.register(make("greeter"))
    r.register(make("news_hound"))
    listing = r.list()
    assert len(listing) == 2
    for entry in listing:
        assert set(entry.keys()) == {"name", "title"}


def test_replace_overwrites_existing_entry_without_raising():
    r = ClassRegistry()
    r.register(make("greeter", "original.yaml"))
    r.replace(make("greeter", "edited.yaml"))
    assert r.get("greeter").source_path == Path("edited.yaml")


def test_replace_works_on_a_fresh_name_too():
    r = ClassRegistry()
    r.replace(make("greeter"))
    assert r.get("greeter").name == "greeter"
