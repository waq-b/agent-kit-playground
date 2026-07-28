"""stat_mapping — deterministic mapping from character stats to Pydantic AI runtime parameters.

Pure functions, no I/O. This is where "stats influence how an agent runs" is
decided in plain code — the LLM never sees or reasons about its own stats.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_kit.class_definition import DEFAULT_BASE_STAT_VALUE


@dataclass(frozen=True)
class RuntimeParams:
    temperature: float
    retries: int
    tool_timeout: float
    max_concurrency: int


def compute_temperature(base_temperature: float, reliability: int) -> float:
    """Higher Reliability -> lower temperature (steadier output), clamped [0.0, 2.0]."""
    factor = 1 - 0.5 * (reliability / 100)
    return round(max(0.0, min(2.0, base_temperature * factor)), 4)


def compute_retries(accuracy: int) -> int:
    """Higher Accuracy -> more output-validation retries. Range [1, 5]."""
    return 1 + round((accuracy / 100) * 4)


def compute_tool_timeout(speed: int, max_tool_tier: int = 0) -> float:
    """Higher Speed -> shorter timeout (less patience); each tool-proficiency tier
    further shaves 1s off (practiced agents decide faster), floored at 5.0s."""
    base = max(10.0, 30.0 - (speed / 100) * 20.0)
    return max(5.0, base - max_tool_tier * 1.0)


def compute_max_concurrency(speed: int) -> int:
    """Higher Speed -> more concurrent tool calls allowed. Range [1, 4]."""
    return 1 + round((speed / 100) * 3)


def compute_runtime_params(
    base_temperature: float,
    base_stats: dict[str, int],
    tool_tiers: dict[str, int] | None = None,
) -> RuntimeParams:
    reliability = base_stats.get("reliability", DEFAULT_BASE_STAT_VALUE)
    accuracy = base_stats.get("accuracy", DEFAULT_BASE_STAT_VALUE)
    speed = base_stats.get("speed", DEFAULT_BASE_STAT_VALUE)
    max_tier = max(tool_tiers.values(), default=0) if tool_tiers else 0
    return RuntimeParams(
        temperature=compute_temperature(base_temperature, reliability),
        retries=compute_retries(accuracy),
        tool_timeout=compute_tool_timeout(speed, max_tier),
        max_concurrency=compute_max_concurrency(speed),
    )


def compute_tool_emphasis(class_stats: dict[str, int], tools: list[str]) -> list[str]:
    """Extension point for class-stat-driven tool emphasis/reordering.

    Currently inert (returns `tools` unchanged): agent-kit ships exactly one
    real tool (fetch_rss_feed), so reordering a single-element list would be
    arbitrary and untestable in any meaningful sense. Kept as a real, called
    hook so class stats have somewhere to plug in once >=2 tools exist.
    """
    return list(tools)
