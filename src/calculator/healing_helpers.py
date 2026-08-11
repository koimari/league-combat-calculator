"""Shared helpers for champion-owned healing declarations.

Healing is deliberately kept separate from item/stat heuristics.  A result
contains post-mitigation, ordered damage events; this module applies only
champion-specific Wiki rules to those events and returns another ordered
ledger for the participant simulator.
"""

# These names form the compatibility helper surface used by champion modules.
# pylint: disable=too-many-arguments,unused-import

from __future__ import annotations

import re
from typing import Any, Iterable

from .champions.slotlib import extract_named, find_named_leveling, sum_modifiers


def _leveling_value(ability: dict[str, Any], attribute: str, rank: int) -> float:
    """Read one sourced leveling attribute without inventing a fallback."""
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") != attribute:
                continue
            modifiers = leveling.get("modifiers", [])
            if not modifiers:
                return 0.0
            values = modifiers[0].get("values", [])
            if not values:
                return 0.0
            return float(values[min(max(rank, 1) - 1, len(values) - 1)])
    return 0.0


def _leveling_modifier(
    ability: dict[str, Any], attribute: str, rank: int, modifier_index: int = 0
) -> float:
    """Read one sourced leveling modifier at rank without scaling resolution.

    ``extract_named`` sums every modifier and resolves stat-scaling units,
    but a missing-health percentage (e.g. Tahm Kench's ``"% of missing
    health"``) is not a stat the scaling layer knows, so it resolves to 0.0.
    This helper reads the raw percentage value for those formula components;
    the caller folds it into an amount formula evaluated against the
    fighter's live health.
    """
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") != attribute:
                continue
            modifiers = leveling.get("modifiers", [])
            if modifier_index >= len(modifiers):
                return 0.0
            values = modifiers[modifier_index].get("values", [])
            if not values:
                return 0.0
            return float(values[min(max(rank, 1) - 1, len(values) - 1)])
    return 0.0


def _ability(
    champion_data: dict[str, Any], slot: str, index: int = 0
) -> dict[str, Any]:
    entries = champion_data.get("abilities", {}).get(slot, [])
    if index >= len(entries):
        return {}
    return entries[index] if isinstance(entries[index], dict) else {}


def _leveling_ratio(
    ability: dict[str, Any], attribute: str, unit_substring: str, rank: int
) -> float:
    """Read one sourced modifier whose unit contains a substring at rank.

    Some heal attributes mix modifiers with different unit vocabularies
    (flat-per-level, "% AP", "% of his missing health"); ``extract_named``
    resolves the stat-scaling ones but drops units it does not recognize,
    so the missing-health term needs its own targeted read.
    """
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") != attribute:
                continue
            for modifier in leveling.get("modifiers", []):
                units = modifier.get("units", [])
                values = modifier.get("values", [])
                if not units or not values:
                    continue
                if unit_substring.lower() not in str(units[0]).lower():
                    continue
                return float(values[min(max(rank, 1) - 1, len(values) - 1)])
    return 0.0


def _leveling_flat_at_level(
    ability: dict[str, Any], attribute: str, level: int
) -> float:
    """Read the flat (unit-less) modifier of one attribute at champion level."""
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") != attribute:
                continue
            for modifier in leveling.get("modifiers", []):
                values = modifier.get("values", [])
                units = modifier.get("units", [])
                if not values:
                    continue
                if units and str(units[0]).strip():
                    continue
                return float(values[min(max(level, 1) - 1, len(values) - 1)])
    return 0.0


def _level_breakpoint_value(values: list[Any], level: int) -> float:
    """Read a six-value Wiki row at levels 1, 6, 11, 16, 17, and 18."""
    if not values:
        return 0.0
    if len(values) == 6:
        breakpoints = (1, 6, 11, 16, 17, 18)
        for index in range(len(breakpoints) - 1, -1, -1):
            if level >= breakpoints[index]:
                return float(values[index])
        return float(values[0])
    return float(values[min(max(level, 1) - 1, len(values) - 1)])


def _event_source(event: dict[str, Any]) -> str:
    return str(event.get("source_key", ""))


def _taric_starlights_touch(
    q_ability: dict[str, Any],
    q_rank: int,
    champion_stats: dict[str, float],
) -> tuple[float, int]:
    """Price one Taric Q (Starlight's Touch) cast from the cached data.

    The per-charge and maximum formulas are wiki description text in
    ``data/champions.json``; the stock is the rank-scaled "Maximum Charges"
    leveling attribute.  Returns ``(heal_amount, charges_used)`` — the
    amount at the sourced stock, capped at the "maximum of ... at 5
    charges" row, with zero when no per-charge formula or stock exists.
    Issue #143: this is the single formula source for the Q heal; the
    support scanner never re-prices the slot.
    """
    charges = extract_named(q_ability, "Maximum Charges", q_rank, champion_stats, {})
    descriptions = [
        effect.get("description", "") for effect in q_ability.get("effects", [])
    ]
    per_charge_match = re.search(
        r"for\s+(\d+(?:\.\d+)?)\s*\(\+\s*(\d+(?:\.\d+)?)%\s*AP\)"
        r"\s*\(\+\s*(\d+(?:\.\d+)?)%\s*of his maximum health\)\s*per charge",
        " ".join(descriptions),
        flags=re.IGNORECASE,
    )
    maximum_match = re.search(
        r"maximum of\s+(\d+(?:\.\d+)?)\s*\(\+\s*(\d+(?:\.\d+)?)%\s*AP\)"
        r"\s*\(\+\s*(\d+(?:\.\d+)?)%\s*of his maximum health\)",
        " ".join(descriptions),
        flags=re.IGNORECASE,
    )
    if per_charge_match is None or charges <= 0.0:
        return 0.0, max(0, int(round(charges)))
    maximum_health = float(champion_stats.get("health", 0.0) or 0.0)
    ability_power = float(champion_stats.get("ability_power", 0.0) or 0.0)

    def _charge_heal(flat: float, ap_percent: float, hp_percent: float) -> float:
        return (
            flat
            + ability_power * ap_percent / 100.0
            + maximum_health * hp_percent / 100.0
        )

    per_charge = _charge_heal(
        float(per_charge_match.group(1)),
        float(per_charge_match.group(2)),
        float(per_charge_match.group(3)),
    )
    heal = charges * per_charge
    if maximum_match is not None:
        heal = min(
            heal,
            _charge_heal(
                float(maximum_match.group(1)),
                float(maximum_match.group(2)),
                float(maximum_match.group(3)),
            ),
        )
    return max(0.0, heal), max(0, int(round(charges)))


def _is_persistent(event: dict[str, Any]) -> bool:
    """Return the source-certified persistent/periodic damage boundary.

    The engine's own source keys are stable public receipts for these rows;
    no damage amount or champion archetype is guessed here.
    """
    source = _event_source(event).lower()
    return (
        source.startswith("burn_")
        or source.startswith("stacking_dot_")
        or "tibbers_aura" in source
        or source.startswith("immolate_")
    )


def _attributed_events(
    events: Iterable[dict[str, Any]],
    predicate,
) -> list[dict[str, Any]]:
    return [event for event in events if predicate(_event_source(event), event)]


def _rank(ability_damages: dict[str, dict[str, Any]], slot: str) -> int:
    """Use the parser's sourced rank; omitted ranks are already level-derived."""
    try:
        return max(0, int(ability_damages.get(slot, {}).get("rank", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _trigger_fields(event: dict[str, Any]) -> dict[str, Any]:
    """Carry a stable internal receipt for the damage that caused a heal."""
    fields: dict[str, Any] = {
        "_trigger_source": _event_source(event),
        "_trigger_time": float(event.get("time", 0.0)),
    }
    if event.get("sequence") is not None:
        fields["_trigger_sequence"] = int(event["sequence"])
    return fields


def _heal_from_damage(
    healing: list[dict[str, Any]],
    event: dict[str, Any],
    amount: float,
    source: str,
    *,
    later_target_amount: float | None = None,
    link_to_damage: bool = True,
) -> None:
    """Append one sourced self-heal tied to a damage event.

    ``later_target_amount`` is the explicit receipt for a per-champion flat
    heal that pays a reduced amount to targets after the first (Vladimir's
    Hemoplague).  The participant ledger re-prices the heal to that amount
    for every defender past the roster's first target, so each target keeps
    its own event instead of the engine re-authoring the full amount per
    pair fight.

    ``link_to_damage=False`` marks flat heals that trigger at cast/detonation
    regardless of whether the paired damage event landed (Vladimir Q/R); the
    trigger fields still link the receipt to the cast for audit.
    """
    amount = max(0.0, float(amount))
    if amount <= 0.0:
        return
    if link_to_damage and float(event.get("damage", 0.0)) <= 0.0:
        return
    heal: dict[str, Any] = {
        "time": float(event.get("time", 0.0)),
        "amount": amount,
        "source": source,
        "kind": "champion_ability",
        **_trigger_fields(event),
    }
    if later_target_amount is not None:
        heal["_later_target_amount"] = max(0.0, float(later_target_amount))
    healing.append(heal)


def _missing_health_scaled_heal(minimum: float, maximum: float):
    """Build a live missing-health interpolation between two sourced bounds.

    Wiki "0% : 100% (based on missing health)" means the heal pays the
    minimum at full health and the maximum at 0 health, interpolated
    linearly by the recipient's missing-health ratio at the moment the heal
    lands.  The survival walk evaluates the returned callable with the
    recipient's live (current, maximum) health.
    """
    minimum = max(0.0, float(minimum))
    maximum = max(minimum, float(maximum))

    def amount_formula(current_health: float, maximum_health: float) -> float:
        if maximum_health <= 0.0:
            return minimum
        missing_ratio = max(0.0, maximum_health - current_health) / maximum_health
        return minimum + (maximum - minimum) * missing_ratio

    return amount_formula


def _cast_slot_times(
    cast_timeline: list[dict[str, Any]] | None, slot: str
) -> list[float]:
    """Ordered cast times for one slot from the engine's cast timeline."""
    return sorted(
        float(cast.get("time", 0.0))
        for cast in (cast_timeline or [])
        if cast.get("slot") == slot
    )


# Compatibility names for the reviewed self-healing rules. The public
# ``healing.py`` entrypoint loads typed declarations from champion modules and
# keeps this set during the formula migration. The scoring fast path reads the
