import pytest

from agent_kit.stat_mapping import (
    compute_max_concurrency,
    compute_retries,
    compute_runtime_params,
    compute_temperature,
    compute_tool_emphasis,
    compute_tool_timeout,
)


@pytest.mark.parametrize(
    "reliability,base_temp,expected",
    [(0, 1.0, 1.0), (50, 1.0, 0.75), (100, 1.0, 0.5)],
)
def test_compute_temperature_boundaries(reliability, base_temp, expected):
    assert compute_temperature(base_temp, reliability) == expected


def test_compute_temperature_clamped_to_valid_range():
    assert 0.0 <= compute_temperature(2.0, 0) <= 2.0
    assert 0.0 <= compute_temperature(2.0, 100) <= 2.0


@pytest.mark.parametrize("accuracy,expected", [(0, 1), (50, 3), (100, 5)])
def test_compute_retries_boundaries(accuracy, expected):
    assert compute_retries(accuracy) == expected


@pytest.mark.parametrize("speed,expected", [(0, 30.0), (50, 20.0), (100, 10.0)])
def test_compute_tool_timeout_boundaries_no_tier(speed, expected):
    assert compute_tool_timeout(speed, max_tool_tier=0) == expected


def test_compute_tool_timeout_reduced_by_tool_tier_but_floored():
    assert compute_tool_timeout(speed=100, max_tool_tier=2) == 8.0
    assert compute_tool_timeout(speed=100, max_tool_tier=50) == 5.0  # floor


@pytest.mark.parametrize("speed,expected", [(0, 1), (50, 3), (100, 4)])
def test_compute_max_concurrency_boundaries(speed, expected):
    assert compute_max_concurrency(speed) == expected


def test_compute_runtime_params_integration():
    params = compute_runtime_params(
        base_temperature=0.7,
        base_stats={"accuracy": 100, "insight": 50, "speed": 100, "reliability": 100},
        tool_tiers={"fetch_rss_feed": 2},
    )
    assert params.temperature == compute_temperature(0.7, 100)
    assert params.retries == 5
    assert params.tool_timeout == compute_tool_timeout(100, 2)
    assert params.max_concurrency == 4


def test_compute_runtime_params_defaults_missing_stats_to_50():
    params = compute_runtime_params(base_temperature=0.7, base_stats={})
    assert params.retries == compute_retries(50)


def test_compute_tool_emphasis_is_currently_a_passthrough():
    tools = ["fetch_rss_feed"]
    assert compute_tool_emphasis({"source_nose": 90}, tools) == tools
    assert compute_tool_emphasis({}, []) == []
