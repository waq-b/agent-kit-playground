from pathlib import Path

import pytest

from agent_kit.card_definition import CardDefinition
from agent_kit.card_store import CardStore
from agent_kit.class_definition import ClassDefinition
from agent_kit.registry import get_registry
from tests.conftest import make_stat
from agent_kit.errors import (
    AgentCardNotFoundError,
    GMSuggestionNotFoundError,
    UnknownGradeActionError,
)

SOURCE = Path("test.yaml")


def make_card(base_stats=None) -> CardDefinition:
    main_class = ClassDefinition(
        name="greeter", title="Greeter", description="d", stats={"warmth": make_stat(65)}, source_path=SOURCE
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
    store.store_traits("hello", "sig", "paragraph")
    store.record_suggestion("hello", "old", "new", "why")
    store.clear()
    with pytest.raises(AgentCardNotFoundError):
        store.get_state("hello")
    assert store.get_traits("hello") is None
    assert store.list_suggestions(None) == []


# --- GM trait cache / respec debuff / suggestions (v0.4) ---


def test_get_traits_is_none_before_any_synthesis():
    assert CardStore(":memory:").get_traits("hello") is None


def test_store_and_get_traits_round_trip():
    store = CardStore(":memory:")
    store.store_traits("hello", "warmth=high", "You are warm.")
    traits = store.get_traits("hello")
    assert traits.trait_paragraph == "You are warm."
    assert traits.band_signature == "warmth=high"
    assert traits.is_stale is False
    assert traits.pending_since is None


def test_mark_traits_stale_applies_debuff_and_queues():
    store = CardStore(":memory:")
    store.store_traits("hello", "sig", "paragraph")
    store.mark_traits_stale("hello")

    traits = store.get_traits("hello")
    assert traits.is_stale is True
    assert traits.pending_since is not None
    assert [t.agent_name for t in store.list_stale_agents()] == ["hello"]


def test_repeated_failures_preserve_original_queue_position():
    """pending_since must not reset on each retry, or a repeatedly-failing agent
    would keep jumping to the back of the queue."""
    store = CardStore(":memory:")
    store.store_traits("hello", "sig", "paragraph")
    store.mark_traits_stale("hello")
    first = store.get_traits("hello").pending_since
    store.mark_traits_stale("hello")
    assert store.get_traits("hello").pending_since == first


def test_store_traits_clears_debuff_and_queue():
    store = CardStore(":memory:")
    store.store_traits("hello", "old-sig", "old paragraph")
    store.mark_traits_stale("hello")
    store.store_traits("hello", "new-sig", "new paragraph")

    traits = store.get_traits("hello")
    assert traits.is_stale is False
    assert traits.pending_since is None
    assert traits.trait_paragraph == "new paragraph"
    assert store.list_stale_agents() == []


def test_mark_traits_stale_is_a_noop_without_a_cached_row():
    """Nothing to flag when the GM failed before any successful synthesis —
    the caller uses the deterministic fallback for that run instead."""
    store = CardStore(":memory:")
    store.mark_traits_stale("never_cached")
    assert store.get_traits("never_cached") is None
    assert store.list_stale_agents() == []


def test_suggestion_lifecycle():
    store = CardStore(":memory:")
    suggestion = store.record_suggestion("hello", "old prompt", "new prompt", "rationale")
    assert suggestion.status == "pending"
    assert [s.id for s in store.list_suggestions()] == [suggestion.id]

    resolved = store.resolve_suggestion(suggestion.id, "approved")
    assert resolved.status == "approved"
    assert store.list_suggestions("pending") == []
    assert len(store.list_suggestions(None)) == 1


def test_unknown_suggestion_id_raises():
    store = CardStore(":memory:")
    with pytest.raises(GMSuggestionNotFoundError):
        store.get_suggestion(9999)
    with pytest.raises(GMSuggestionNotFoundError):
        store.resolve_suggestion(9999, "approved")


def test_concurrent_reads_do_not_corrupt_the_shared_connection(tmp_path):
    """A single sqlite3 connection is not safe for concurrent use.

    FastAPI runs the playground's sync endpoints in a threadpool, so any two
    overlapping requests can call execute() on the same connection at once. Left
    unguarded that raises "bad parameter or other API misuse" — which is exactly
    what the Roster hit once the frontend started fetching card details in
    parallel. Every statement now goes through the store's lock.
    """
    import threading

    store = CardStore(str(tmp_path / "concurrent.db"))
    definition = get_registry().get("hello")
    store.ensure_seeded("hello", definition.card)
    store.store_traits("hello", "sig", "a paragraph")
    store.record_suggestion("hello", "old", "new", "why")

    errors: list[str] = []
    barrier = threading.Barrier(8)

    def hammer() -> None:
        barrier.wait()  # maximise overlap rather than hoping for it
        try:
            for _ in range(200):
                store.get_state("hello")
                store.get_traits("hello")
                store.list_stale_agents()
                store.list_suggestions(None)
                store.count_events_since_synthesis("hello")
        except Exception as e:  # noqa: BLE001 — any exception is a failure here
            errors.append(repr(e))

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []


def test_concurrent_reads_and_writes_do_not_corrupt_the_connection(tmp_path):
    """Writes already took the lock; this pins that readers can't race them."""
    import threading

    store = CardStore(str(tmp_path / "mixed.db"))
    definition = get_registry().get("hello")
    store.ensure_seeded("hello", definition.card)

    errors: list[str] = []
    barrier = threading.Barrier(6)

    def read() -> None:
        barrier.wait()
        try:
            for _ in range(150):
                store.get_state("hello")
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))

    def write() -> None:
        barrier.wait()
        try:
            for _ in range(150):
                store.record_xp_event("hello", "thumbs_up")
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))

    threads = [threading.Thread(target=read) for _ in range(3)]
    threads += [threading.Thread(target=write) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
