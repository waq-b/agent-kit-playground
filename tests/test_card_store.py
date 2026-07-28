from pathlib import Path

import pytest

from agent_kit.card_definition import CardDefinition
from agent_kit.card_store import CardStore
from agent_kit.class_definition import ClassDefinition
from agent_kit.errors import AgentCardNotFoundError, UnknownGradeActionError

SOURCE = Path("test.yaml")


def make_card(base_stats=None) -> CardDefinition:
    main_class = ClassDefinition(
        name="greeter", title="Greeter", description="d", stats={"warmth": 65}, source_path=SOURCE
    )
    return CardDefinition(
        title="Greeter", backstory="b", portrait="👋", main_class=main_class, sub_class=None,
        class_stats={"warmth": 65},
        base_stats=base_stats or {"accuracy": 50, "insight": 50, "speed": 50, "reliability": 50},
        unlock_table=(), starting_level=1, starting_xp=0,
    )


def test_ensure_seeded_then_get_state():
    store = CardStore(":memory:")
    store.ensure_seeded("hello", make_card())
    state = store.get_state("hello")
    assert state.agent_name == "hello"
    assert state.level == 1
    assert state.xp == 0
    assert state.base_stats == {"accuracy": 50, "insight": 50, "speed": 50, "reliability": 50}
    assert state.class_stats == {"warmth": 65}
    assert state.tool_proficiency == {}


def test_ensure_seeded_is_idempotent():
    store = CardStore(":memory:")
    store.ensure_seeded("hello", make_card())
    store.record_xp_event("hello", "thumbs_up")  # mutate state
    store.ensure_seeded("hello", make_card())  # should be a no-op, not reset xp
    state = store.get_state("hello")
    assert state.xp == 10  # unchanged by second ensure_seeded call


def test_get_state_before_seeding_raises_agent_card_not_found_error():
    store = CardStore(":memory:")
    with pytest.raises(AgentCardNotFoundError):
        store.get_state("never_seeded")


def test_record_xp_event_updates_xp_and_level():
    store = CardStore(":memory:")
    store.ensure_seeded("hello", make_card())
    result = store.record_xp_event("hello", "thumbs_up")
    assert result.xp_delta == 10
    assert result.new_xp == 10
    assert result.new_level == 1
    assert result.leveled_up is False

    state = store.get_state("hello")
    assert state.xp == 10


def test_record_xp_event_triggers_level_up():
    store = CardStore(":memory:")
    store.ensure_seeded("hello", make_card())
    for _ in range(5):
        result = store.record_xp_event("hello", "thumbs_up")  # 5 * 10 = 50 xp -> level 2
    assert result.new_level == 2
    assert result.leveled_up is True


def test_record_xp_event_nudges_stats_and_reports_actual_deltas():
    store = CardStore(":memory:")
    store.ensure_seeded("hello", make_card())
    result = store.record_xp_event("hello", "thumbs_up")
    state = store.get_state("hello")
    assert state.base_stats["accuracy"] == 52  # nudged +2 (magnitude = max(1, 10//5))
    assert result.stat_deltas["accuracy"] == 2


def test_record_xp_event_clamps_stats_to_0_100():
    store = CardStore(":memory:")
    store.ensure_seeded("hello", make_card(base_stats={"accuracy": 99, "insight": 1, "speed": 50, "reliability": 50}))
    result = store.record_xp_event("hello", "thumbs_up")  # +2 nudge would push accuracy to 101
    state = store.get_state("hello")
    assert state.base_stats["accuracy"] == 100
    assert result.stat_deltas["accuracy"] == 1  # actual delta applied, not the raw +2 nudge

    store.record_xp_event("hello", "thumbs_down")  # -1 nudge on insight=1 would go to 0, fine
    store.record_xp_event("hello", "thumbs_down")
    store.record_xp_event("hello", "thumbs_down")
    state = store.get_state("hello")
    assert state.base_stats["insight"] >= 0  # never goes negative


def test_record_xp_event_tracks_tool_proficiency():
    store = CardStore(":memory:")
    store.ensure_seeded("hello", make_card())
    store.record_xp_event("hello", "thumbs_up", tool_used="fetch_rss_feed")
    state = store.get_state("hello")
    assert state.tool_proficiency["fetch_rss_feed"].xp == 10
    assert state.tool_proficiency["fetch_rss_feed"].tier == 0  # floor(10/20) = 0

    for _ in range(4):
        store.record_xp_event("hello", "thumbs_up", tool_used="fetch_rss_feed")
    state = store.get_state("hello")
    assert state.tool_proficiency["fetch_rss_feed"].xp == 50
    assert state.tool_proficiency["fetch_rss_feed"].tier == 2  # floor(50/20) = 2


def test_record_xp_event_unknown_action_raises():
    store = CardStore(":memory:")
    store.ensure_seeded("hello", make_card())
    with pytest.raises(UnknownGradeActionError):
        store.record_xp_event("hello", "not_a_real_action")


def test_record_xp_event_before_seeding_raises_agent_card_not_found_error():
    store = CardStore(":memory:")
    with pytest.raises(AgentCardNotFoundError):
        store.record_xp_event("never_seeded", "thumbs_up")


def test_clear_removes_all_state():
    store = CardStore(":memory:")
    store.ensure_seeded("hello", make_card())
    store.record_xp_event("hello", "thumbs_up", tool_used="fetch_rss_feed")
    store.clear()
    with pytest.raises(AgentCardNotFoundError):
        store.get_state("hello")
