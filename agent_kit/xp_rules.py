"""xp_rules — deterministic rules converting graded feedback into XP, stat, and level changes.

Pure functions, no I/O. The LLM is never asked to score itself; all of this is
plain, testable arithmetic driven by user grading actions.
"""

from __future__ import annotations

from typing import Iterable

from agent_kit.errors import UnknownGradeActionError

_ACTION_XP_TABLE: dict[str, int] = {
    "thumbs_up": 10,
    "thumbs_down": -5,
    "more_like_this": 6,
    "less_like_this": -3,
    "implicit_view": 2,
}

_ACTION_GRADE_TABLE: dict[str, str] = {
    "thumbs_up": "positive",
    "thumbs_down": "negative",
    "more_like_this": "positive",
    "less_like_this": "negative",
    "implicit_view": "neutral",
}

_XP_PER_LEVEL = 50
_TOOL_XP_PER_TIER = 20
_STAT_NUDGE_DIVISOR = 5


def compute_xp_delta(action: str) -> int:
    if action not in _ACTION_XP_TABLE:
        raise UnknownGradeActionError(f"unknown grading action '{action}'")
    return _ACTION_XP_TABLE[action]


def grade_for_action(action: str) -> str:
    if action not in _ACTION_GRADE_TABLE:
        raise UnknownGradeActionError(f"unknown grading action '{action}'")
    return _ACTION_GRADE_TABLE[action]


def compute_level(total_xp: int) -> int:
    """1 + floor(max(total_xp,0) / 50). Never below 1; monotonic non-decreasing in total_xp."""
    return 1 + max(0, total_xp) // _XP_PER_LEVEL


def compute_stat_nudge(stat_names: Iterable[str], xp_delta: int) -> dict[str, int]:
    """Documented simplification: every graded event nudges *all* given stats
    uniformly by a small signed amount derived from the event's XP delta — the
    spec doesn't define a per-action-to-specific-stat mapping, so this is the
    simplest defensible rule. Caller (CardStore) clamps results to [0, 100]."""
    if xp_delta == 0:
        return {name: 0 for name in stat_names}
    magnitude = max(1, abs(xp_delta) // _STAT_NUDGE_DIVISOR)
    nudge = magnitude if xp_delta > 0 else -magnitude
    return {name: nudge for name in stat_names}


def compute_tool_tier(tool_xp: int) -> int:
    """floor(max(tool_xp,0) / 20), independent of agent level."""
    return max(0, tool_xp) // _TOOL_XP_PER_TIER
