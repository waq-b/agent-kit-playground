import pytest

from agent_kit.stat_effects import (
    PromptBand,
    RuntimeCurve,
    StatDefinition,
    apply_runtime_deltas,
    band_signature,
    fallback_trait_paragraph,
    interpolate_delta,
    resolve_effects,
    select_band,
)
from agent_kit.stat_mapping import RuntimeParams


def bands(*labels):
    return tuple(PromptBand(label=label, text=f"{label}-text") for label in labels)


FOUR = bands("a", "b", "c", "d")


@pytest.mark.parametrize(
    "value,expected",
    [(0, "a"), (24, "a"), (25, "b"), (49, "b"), (50, "c"), (65, "c"), (74, "c"), (75, "d"), (99, "d")],
)
def test_select_band_four_band_boundaries(value, expected):
    assert select_band(FOUR, value).label == expected


def test_select_band_value_100_stays_in_last_band():
    """The min() guard in select_band exists for exactly this case — without it,
    100 computes an index of len(bands) and raises IndexError."""
    assert select_band(FOUR, 100).label == "d"


def test_select_band_single_band_always_matches():
    single = bands("only")
    assert select_band(single, 0).label == "only"
    assert select_band(single, 50).label == "only"
    assert select_band(single, 100).label == "only"


def test_select_band_five_bands():
    five = bands("0", "1", "2", "3", "4")
    assert select_band(five, 0).label == "0"
    assert select_band(five, 100).label == "4"
    assert select_band(five, 45).label == "2"


def test_select_band_clamps_out_of_range_values():
    assert select_band(FOUR, -50).label == "a"
    assert select_band(FOUR, 500).label == "d"


def test_select_band_empty_raises():
    with pytest.raises(ValueError):
        select_band((), 50)


def test_interpolate_delta_endpoints_and_midpoint():
    curve = RuntimeCurve(at_0=0.1, at_100=-0.2)
    assert interpolate_delta(curve, 0) == pytest.approx(0.1)
    assert interpolate_delta(curve, 100) == pytest.approx(-0.2)
    assert interpolate_delta(curve, 50) == pytest.approx(-0.05)


def test_resolve_effects_uses_authored_value_when_no_current_value():
    defs = {
        "warmth": StatDefinition(
            value=80, prompt_effect=bands("low", "high"),
            runtime_effect={"temperature": RuntimeCurve(at_0=0.0, at_100=0.2)},
        )
    }
    resolved = resolve_effects(defs)
    assert resolved.selected_bands["warmth"].label == "high"
    assert resolved.runtime_deltas["temperature"] == pytest.approx(0.16)


def test_resolve_effects_current_value_overrides_authored_value():
    defs = {
        "warmth": StatDefinition(
            value=80, prompt_effect=bands("low", "high"),
            runtime_effect={"temperature": RuntimeCurve(at_0=0.0, at_100=0.2)},
        )
    }
    resolved = resolve_effects(defs, {"warmth": 10})
    assert resolved.selected_bands["warmth"].label == "low"


def test_resolve_effects_sums_deltas_across_multiple_stats():
    defs = {
        "warmth": StatDefinition(
            value=80, prompt_effect=bands("low", "high"),
            runtime_effect={"temperature": RuntimeCurve(at_0=0.0, at_100=0.2)},
        ),
        "rigor": StatDefinition(
            value=20, prompt_effect=bands("low", "high"),
            runtime_effect={"temperature": RuntimeCurve(at_0=0.0, at_100=-0.4)},
        ),
    }
    resolved = resolve_effects(defs)
    # warmth 80 -> +0.16, rigor 20 -> -0.08, summed
    assert resolved.runtime_deltas["temperature"] == pytest.approx(0.08)


def test_band_signature_is_sorted_and_order_independent():
    selected = {"warmth": PromptBand("high", "t"), "rigor": PromptBand("low", "t")}
    reversed_order = {k: selected[k] for k in reversed(list(selected))}
    assert band_signature(selected) == "rigor=low|warmth=high"
    assert band_signature(selected) == band_signature(reversed_order)


def test_band_signature_changes_only_when_band_changes():
    low = {"warmth": PromptBand("low", "t")}
    high = {"warmth": PromptBand("high", "t")}
    assert band_signature(low) != band_signature(high)


BASE = RuntimeParams(temperature=0.7, retries=3, tool_timeout=20.0, max_concurrency=2)


def test_apply_runtime_deltas_adds_to_base():
    result = apply_runtime_deltas(BASE, {"temperature": 0.08, "retries": 0.6})
    assert result.temperature == pytest.approx(0.78)
    assert result.retries == 4  # 3.6 rounds to 4


def test_apply_runtime_deltas_clamps_upper_bounds():
    result = apply_runtime_deltas(
        BASE, {"temperature": 99, "retries": 99, "tool_timeout": 9999, "max_concurrency": 99}
    )
    assert (result.temperature, result.retries, result.tool_timeout, result.max_concurrency) == (
        2.0, 10, 120.0, 8,
    )


def test_apply_runtime_deltas_clamps_lower_bounds():
    result = apply_runtime_deltas(
        BASE, {"temperature": -99, "retries": -99, "tool_timeout": -9999, "max_concurrency": -99}
    )
    assert (result.temperature, result.retries, result.tool_timeout, result.max_concurrency) == (
        0.0, 1, 1.0, 1,
    )


def test_apply_runtime_deltas_with_no_deltas_is_identity():
    assert apply_runtime_deltas(BASE, {}) == BASE


def test_apply_runtime_deltas_ignores_unknown_parameters():
    assert apply_runtime_deltas(BASE, {"not_a_real_param": 5}) == BASE


def test_fallback_trait_paragraph_joins_sorted_texts():
    selected = {"warmth": PromptBand("high", "Warm text."), "rigor": PromptBand("low", "Rigor text.")}
    assert fallback_trait_paragraph(selected) == "Rigor text. Warm text."


def test_fallback_trait_paragraph_empty():
    assert fallback_trait_paragraph({}) == ""
