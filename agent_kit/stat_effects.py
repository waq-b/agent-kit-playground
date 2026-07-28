"""stat_effects — deterministic resolution of custom class stats into prompt and runtime effects.

Pure functions, no I/O, no LLM. Given a class's authored stat definitions and
an agent's *current* stat values, this decides which prompt fragment applies
and how much each stat nudges the execution parameters. The GM (see gm.py)
only ever smooths the selected fragments into readable prose — it never picks
them, and it never touches the runtime numbers.

Runtime effects are **deltas**, not absolutes: each stat contributes a modifier
layered on top of the base-stat values from stat_mapping.py, exactly the way
modifiers stack in a tabletop game. That is what makes several stats (and a
main class plus a sub class) combinable at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_kit.stat_mapping import RuntimeParams

#: Runtime parameters a stat's runtime_effect is allowed to modify — the four
#: real fields of RuntimeParams, each with the range its summed result is
#: clamped to. Anything outside this mapping is a load-time error.
RUNTIME_PARAMETER_BOUNDS: dict[str, tuple[float, float]] = {
    "temperature": (0.0, 2.0),
    "retries": (1, 10),
    "tool_timeout": (1.0, 120.0),
    "max_concurrency": (1, 8),
}

_INTEGER_PARAMETERS = frozenset({"retries", "max_concurrency"})


@dataclass(frozen=True)
class PromptBand:
    label: str
    text: str


@dataclass(frozen=True)
class RuntimeCurve:
    at_0: float
    at_100: float


@dataclass(frozen=True)
class StatDefinition:
    value: int
    prompt_effect: tuple[PromptBand, ...]
    runtime_effect: dict[str, RuntimeCurve]


@dataclass(frozen=True)
class ResolvedEffects:
    selected_bands: dict[str, PromptBand]
    runtime_deltas: dict[str, float]


def select_band(bands: tuple[PromptBand, ...], value: int) -> PromptBand:
    """Pick the band a 0-100 value falls into, splitting the range into N equal widths.

    The min() keeps value=100 inside the final band instead of overflowing to
    an index of N.
    """
    if not bands:
        raise ValueError("cannot select a band from an empty band list")
    clamped = max(0, min(100, value))
    index = min(int(clamped / 100 * len(bands)), len(bands) - 1)
    return bands[index]


def interpolate_delta(curve: RuntimeCurve, value: int) -> float:
    """Linearly interpolate a stat's runtime delta across its 0-100 value range."""
    clamped = max(0, min(100, value))
    return curve.at_0 + (curve.at_100 - curve.at_0) * (clamped / 100)


def resolve_effects(
    stat_defs: dict[str, StatDefinition],
    current_values: dict[str, int] | None = None,
) -> ResolvedEffects:
    """Join authored stat definitions with an agent's current values.

    `current_values` (from CardStore, where XP nudges land) takes precedence
    over the class definition's authored starting `value` when present.
    """
    current_values = current_values or {}
    selected_bands: dict[str, PromptBand] = {}
    runtime_deltas: dict[str, float] = {}

    for stat_name, definition in stat_defs.items():
        value = current_values.get(stat_name, definition.value)
        selected_bands[stat_name] = select_band(definition.prompt_effect, value)
        for parameter, curve in definition.runtime_effect.items():
            runtime_deltas[parameter] = runtime_deltas.get(parameter, 0.0) + interpolate_delta(curve, value)

    return ResolvedEffects(selected_bands=selected_bands, runtime_deltas=runtime_deltas)


def band_signature(selected_bands: dict[str, PromptBand]) -> str:
    """Stable cache key for a set of selected bands.

    Sorted by stat name so it is independent of dict ordering; changes only
    when a stat actually crosses a band boundary, which is precisely when the
    GM's synthesized trait paragraph needs regenerating.
    """
    return "|".join(f"{name}={selected_bands[name].label}" for name in sorted(selected_bands))


def apply_runtime_deltas(base: RuntimeParams, deltas: dict[str, float]) -> RuntimeParams:
    """Add stat deltas to the base-stat-derived params, then clamp each to its range."""
    values: dict[str, float] = {
        "temperature": base.temperature,
        "retries": base.retries,
        "tool_timeout": base.tool_timeout,
        "max_concurrency": base.max_concurrency,
    }

    for parameter, delta in deltas.items():
        if parameter not in RUNTIME_PARAMETER_BOUNDS:
            continue  # unknown params are rejected at load time; ignore defensively here
        low, high = RUNTIME_PARAMETER_BOUNDS[parameter]
        values[parameter] = max(low, min(high, values[parameter] + delta))

    return RuntimeParams(
        temperature=round(values["temperature"], 4),
        retries=int(round(values["retries"])),
        tool_timeout=round(values["tool_timeout"], 4),
        max_concurrency=int(round(values["max_concurrency"])),
    )


def fallback_trait_paragraph(selected_bands: dict[str, PromptBand]) -> str:
    """Deterministic, GM-free assembly of the selected fragments.

    Used in stub mode (so the offline test suite never needs a model) and as
    the last-resort fallback when the GM is unavailable and no previously
    synthesized paragraph is cached. Deliberately plain: this is the
    "prompt soup" the GM exists to improve on, not a replacement for it.
    """
    if not selected_bands:
        return ""
    return " ".join(selected_bands[name].text for name in sorted(selected_bands))
