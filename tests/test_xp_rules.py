import pytest

from agent_kit.errors import UnknownGradeActionError
from agent_kit.xp_rules import (
    compute_level,
    compute_stat_nudge,
    compute_tool_tier,
    compute_xp_delta,
    grade_for_action,
)


@pytest.mark.parametrize(
    "action,expected_delta,expected_grade",
    [
        ("thumbs_up", 10, "positive"),
        ("thumbs_down", -5, "negative"),
        ("more_like_this", 6, "positive"),
        ("less_like_this", -3, "negative"),
        ("implicit_view", 2, "neutral"),
    ],
)
def test_known_actions_have_expected_delta_and_grade(action, expected_delta, expected_grade):
    assert compute_xp_delta(action) == expected_delta
    assert grade_for_action(action) == expected_grade


def test_unknown_action_raises_unknown_grade_action_error():
    with pytest.raises(UnknownGradeActionError):
        compute_xp_delta("not_a_real_action")
    with pytest.raises(UnknownGradeActionError):
        grade_for_action("not_a_real_action")


@pytest.mark.parametrize(
    "total_xp,expected_level",
    [(0, 1), (49, 1), (50, 2), (99, 2), (100, 3), (-100, 1)],
)
def test_compute_level_thresholds(total_xp, expected_level):
    assert compute_level(total_xp) == expected_level


def test_compute_level_never_decreases_as_xp_increases():
    prev_level = compute_level(0)
    for xp in range(0, 500, 7):
        level = compute_level(xp)
        assert level >= prev_level
        prev_level = level


def test_compute_stat_nudge_positive_delta():
    nudges = compute_stat_nudge(["accuracy", "insight"], xp_delta=10)
    assert nudges == {"accuracy": 2, "insight": 2}


def test_compute_stat_nudge_negative_delta():
    nudges = compute_stat_nudge(["accuracy"], xp_delta=-5)
    assert nudges == {"accuracy": -1}


def test_compute_stat_nudge_zero_delta():
    nudges = compute_stat_nudge(["accuracy"], xp_delta=0)
    assert nudges == {"accuracy": 0}


def test_compute_stat_nudge_small_delta_still_has_minimum_magnitude_one():
    nudges = compute_stat_nudge(["accuracy"], xp_delta=2)
    assert nudges == {"accuracy": 1}
    nudges = compute_stat_nudge(["accuracy"], xp_delta=-2)
    assert nudges == {"accuracy": -1}


@pytest.mark.parametrize(
    "tool_xp,expected_tier",
    [(0, 0), (19, 0), (20, 1), (39, 1), (40, 2), (-10, 0)],
)
def test_compute_tool_tier_thresholds(tool_xp, expected_tier):
    assert compute_tool_tier(tool_xp) == expected_tier
