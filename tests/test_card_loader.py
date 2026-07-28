from pathlib import Path

import pytest

from agent_kit.card_loader import parse_card
from agent_kit.class_definition import ClassDefinition
from agent_kit.class_registry import get_class_registry
from agent_kit.errors import (
    ClassNotFoundError,
    InvalidUnlockTableError,
    MissingFieldError,
    StatRangeError,
    UnknownStatError,
)

SOURCE = Path("test_agent.yaml")


@pytest.fixture(autouse=True)
def _isolated_class_registry():
    get_class_registry().clear()
    get_class_registry().register(
        ClassDefinition(name="greeter", title="Greeter", description="d", stats={"warmth": 60}, source_path=SOURCE)
    )
    get_class_registry().register(
        ClassDefinition(
            name="news_hound", title="News Hound", description="d",
            stats={"relevance_sense": 65, "source_nose": 55}, source_path=SOURCE,
        )
    )
    get_class_registry().register(
        ClassDefinition(
            name="investigator", title="Investigator", description="d",
            stats={"skepticism": 70, "source_nose": 90}, source_path=SOURCE,  # deliberate collision on source_nose
        )
    )
    yield
    get_class_registry().clear()


def test_main_class_only_card():
    card = parse_card({"main_class": "greeter"}, SOURCE)
    assert card.title == "Greeter"
    assert card.main_class.name == "greeter"
    assert card.sub_class is None
    assert card.class_stats == {"warmth": 60}
    assert card.base_stats == {"accuracy": 50, "insight": 50, "speed": 50, "reliability": 50}
    assert card.unlock_table == ()
    assert card.starting_level == 1
    assert card.starting_xp == 0


def test_main_and_sub_class_card_merges_stats_sub_wins_collision():
    card = parse_card({"main_class": "news_hound", "sub_class": "investigator"}, SOURCE)
    assert card.title == "News Hound Investigator"
    assert card.sub_class.name == "investigator"
    # source_nose is defined by both classes (55 vs 90) -> sub_class (investigator) wins
    assert card.class_stats == {"relevance_sense": 65, "source_nose": 90, "skepticism": 70}


def test_explicit_title_overrides_auto_derivation():
    card = parse_card({"main_class": "greeter", "title": "Custom Title"}, SOURCE)
    assert card.title == "Custom Title"


def test_unknown_main_class_raises_class_not_found_error():
    with pytest.raises(ClassNotFoundError):
        parse_card({"main_class": "nonexistent"}, SOURCE)


def test_missing_main_class_raises_missing_field_error():
    with pytest.raises(MissingFieldError):
        parse_card({}, SOURCE)


def test_unknown_base_stat_key_raises_unknown_stat_error():
    with pytest.raises(UnknownStatError):
        parse_card({"main_class": "greeter", "base_stats": {"charisma": 50}}, SOURCE)


def test_out_of_range_base_stat_value_raises_stat_range_error():
    with pytest.raises(StatRangeError):
        parse_card({"main_class": "greeter", "base_stats": {"accuracy": 150}}, SOURCE)


def test_base_stats_override_applies_correctly():
    card = parse_card({"main_class": "greeter", "base_stats": {"accuracy": 70}}, SOURCE)
    assert card.base_stats["accuracy"] == 70
    assert card.base_stats["insight"] == 50  # untouched, default


def test_malformed_unlock_table_entry_missing_fields_raises():
    with pytest.raises(InvalidUnlockTableError):
        parse_card({"main_class": "greeter", "unlock_table": [{"level": 2}]}, SOURCE)


def test_malformed_unlock_table_entry_bad_level_raises():
    with pytest.raises(InvalidUnlockTableError):
        parse_card({"main_class": "greeter", "unlock_table": [{"level": 0, "unlock": "x"}]}, SOURCE)


def test_valid_unlock_table_parses_correctly():
    card = parse_card(
        {"main_class": "greeter", "unlock_table": [{"level": 2, "unlock": "Cheerful Aside", "description": "desc"}]},
        SOURCE,
    )
    assert len(card.unlock_table) == 1
    assert card.unlock_table[0].level == 2
    assert card.unlock_table[0].unlock == "Cheerful Aside"
    assert card.unlock_table[0].description == "desc"
