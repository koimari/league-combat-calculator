"""Shared helpers for champion-owned healing declarations.

Healing is deliberately kept separate from item/stat heuristics.  A result
contains post-mitigation, ordered damage events; a champion module's
``derive_self_healing`` applies its own Wiki rules to those events and
returns another ordered ledger for the participant simulator.  This module
is the one home for what those resolvers share: the sourced readers, and
the payment machinery (:class:`HealAnchor`, :func:`payments`) that decides
*how many times* a rule pays — the occasion the Wiki names, never the shape
of the ledger the module happened to author.
"""

# The slotlib readers are re-exported here so a champion module reaches one
# healing surface, and a resolver's parameter list is the shared rule interface.
# pylint: disable=too-many-arguments,unused-import

from __future__ import annotations

from collections.abc import Callable, Container, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

# The event source a heal rule reads: a slot letter, a set of source keys,
# or a predicate over the key.
HealSource = str | Container[str] | Callable[[str], bool]


def modifier_at_rank(
    leveling: Mapping[str, Any], modifier_index: int, rank: int
) -> float:
    """One leveling row's modifier value at ``rank``; 0.0 when it has none."""
    modifiers = leveling.get("modifiers", [])
    if modifier_index >= len(modifiers):
        return 0.0
    values = modifiers[modifier_index].get("values", [])
    if not values:
        return 0.0
    return float(values[min(max(rank, 1) - 1, len(values) - 1)])


def leveling_value(ability: Mapping[str, Any], attribute: str, rank: int) -> float:
    """Read one sourced leveling attribute without inventing a fallback."""
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") != attribute:
                continue
            return modifier_at_rank(leveling, 0, rank)
    return 0.0


def leveling_modifier(
    ability: Mapping[str, Any], attribute: str, rank: int, modifier_index: int = 0
) -> float:
    """Read one sourced leveling modifier at rank, without scaling resolution."""
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") != attribute:
                continue
            return modifier_at_rank(leveling, modifier_index, rank)
    return 0.0


def ability_json(
    champion_data: Mapping[str, Any], slot: str, index: int = 0
) -> dict[str, Any]:
    entries = champion_data.get("abilities", {}).get(slot, [])
    if index >= len(entries):
        return {}
    return entries[index] if isinstance(entries[index], dict) else {}


def leveling_ratio(
    ability: Mapping[str, Any], attribute: str, unit_substring: str, rank: int
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


def event_source(event: Mapping[str, Any]) -> str:
    return str(event.get("source_key", ""))


def attributed_events(
    events: Iterable[dict[str, Any]],
    predicate: Callable[[str, dict[str, Any]], bool],
) -> list[dict[str, Any]]:
    return [event for event in events if predicate(event_source(event), event)]


def parsed_rank(ability_damages: Mapping[str, dict[str, Any]], slot: str) -> int:
    """Use the parser's sourced rank; omitted ranks are already level-derived."""
    try:
        return max(0, int(ability_damages.get(slot, {}).get("rank", 0) or 0))
    except (TypeError, ValueError):
        return 0


def trigger_fields(event: dict[str, Any]) -> dict[str, Any]:
    """Carry a stable internal receipt for the damage that caused a heal."""
    fields: dict[str, Any] = {
        "_trigger_source": event_source(event),
        "_trigger_time": float(event.get("time", 0.0)),
    }
    if event.get("sequence") is not None:
        fields["_trigger_sequence"] = int(event["sequence"])
    return fields


def heal_from_damage(
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
        **trigger_fields(event),
    }
    if later_target_amount is not None:
        heal["_later_target_amount"] = max(0.0, float(later_target_amount))
    healing.append(heal)


def flat_plus_missing_heal(
    flat: float, missing_pct: float
) -> Callable[[float, float], float]:
    """A flat heal plus *missing_pct* percent of the recipient's live missing health."""

    def amount_formula(current_health: float, maximum_health: float) -> float:
        return flat + max(0.0, maximum_health - current_health) * missing_pct / 100.0

    return amount_formula


def missing_health_scaled_heal(
    minimum: float, maximum: float
) -> Callable[[float, float], float]:
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


def cast_slot_times(
    cast_timeline: list[dict[str, Any]] | None, slot: str
) -> list[float]:
    """Ordered cast times for one slot from the engine's cast timeline."""
    return sorted(
        float(cast.get("time", 0.0))
        for cast in (cast_timeline or [])
        if cast.get("slot") == slot
    )


class HealAnchor(Enum):
    """What the game pays one self-heal on — the rule's own answer.

    A self-heal rule reads a damage ledger, but the ledger's *shape* is not
    what the wiki pays on: a champion module that authors an ability's true
    hit cadence turns one row into several events, and a rule that counted
    events would turn one heal into several with it.  So every rule that
    reads the ledger names the occasion it pays on here, and the resolver
    (``healing_helpers.payments``) turns that answer into the payments.

    ``CAST``
        One payment per activation, however many hits the cast authors —
        Frenzied Maul's bite, Void Spike's explosion, Piercing Darkness'
        ray.  The payment lands on the cast's first hit, which is where the
        ability arrives.
    ``DAMAGING_HIT``
        One payment per hit that *dealt damage* — every rule whose amount
        is a share of what the hit did (Severum, Soul Siphon, lifesteal,
        Spirit of Dread).  A hit that dealt nothing pays nothing.
    ``CAST_SCHEDULE``
        The heal has a cadence of its own, counted from the cast, not from
        the damage the cast eventually deals — Chilling Scream heals
        "every 0.25 seconds" *while charging*, before the scream lands.
    """

    CAST = "cast"
    DAMAGING_HIT = "damaging_hit"
    CAST_SCHEDULE = "cast_schedule"


# One cast's events and its cast time can disagree by the rounding the
# engine applies to published cast times (damage.py rounds to 3 decimals
# while authored offsets stay raw), so an event is attributed to the last
# cast at or before it within this slack.
_CAST_MATCH_TOLERANCE = 1e-3


@dataclass(frozen=True, slots=True)
class _Payment:
    """One occasion a self-heal rule pays.

    ``event`` is the damage event the payment rides — the cast's first hit
    for a ``CAST`` payment, the hit itself for a ``DAMAGING_HIT`` one — and
    is what links the heal receipt to the damage that caused it, so a heal
    whose trigger the coupled walk skipped is skipped with it.
    ``cast_time`` is the activation the event belongs to, which is where a
    heal with a cadence of its own starts counting.
    """

    cast_time: float
    event: dict[str, Any]


def _events_matching(
    source: HealSource, damage_events: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Damage events whose source key the rule claims."""
    if callable(source):
        return [event for event in damage_events if source(event_source(event))]
    if isinstance(source, str):
        return [event for event in damage_events if event_source(event) == source]
    return [event for event in damage_events if event_source(event) in source]


def _attributing_cast(cast_times: Iterable[float], event_time: float) -> float | None:
    """The activation an event at *event_time* came from, if one names it."""
    attributed: float | None = None
    for cast_time in cast_times:
        if cast_time <= event_time + _CAST_MATCH_TOLERANCE:
            attributed = cast_time
        else:
            break
    return attributed


def takedown_payments(
    count: int, damage_events: list[dict[str, Any]]
) -> list[_Payment]:
    """The first *count* hits a takedown-paid rule can honestly ride.

    A heal the game pays when a nearby unit dies has no cast and no damage
    row, and a duel simulates neither, so the champion module declares the
    count and the fight supplies the times."""
    if count <= 0:
        return []
    hits = payments(HealAnchor.DAMAGING_HIT, lambda _source: True, damage_events)
    hits.sort(key=lambda payment: payment.cast_time)
    return hits[: int(count)]


def payments(
    anchor: HealAnchor,
    source: HealSource,
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
) -> list[_Payment]:
    """The occasions a rule pays on, per the anchor the rule declares.

    ``source`` is the event source key the rule reads — a slot letter, a
    set of them, or a predicate over the key.  Only a slot letter can be
    matched against the cast timeline, so only that form may anchor on a
    cast.

    The number of payments comes from the declaration, never from how many
    events a champion module authored: a ``CAST`` rule pays once per
    activation whether its module prices the ability as one hit or six.
    When no cast in the timeline names an event (an ability the timeline
    does not publish, or a caller that passed none), each distinct event
    timestamp stands in for its own activation — which keeps the several
    parts of one instant together and is the most a rule can honestly
    conclude without a cast to point at.
    """
    events = _events_matching(source, damage_events)
    if anchor is HealAnchor.DAMAGING_HIT:
        return [
            _Payment(float(event.get("time", 0.0)), event)
            for event in events
            if float(event.get("damage", 0.0) or 0.0) > 0.0
        ]
    if not isinstance(source, str):
        raise ValueError(f"{anchor} needs one slot to match casts, got {source!r}")
    cast_times = cast_slot_times(cast_timeline, source)
    activations: dict[float, dict[str, Any]] = {}
    for event in events:
        event_time = float(event.get("time", 0.0))
        cast_time = _attributing_cast(cast_times, event_time)
        if cast_time is None:
            cast_time = event_time
        held = activations.get(cast_time)
        if held is None or event_time < float(held.get("time", 0.0)):
            activations[cast_time] = event
    return [
        _Payment(cast_time, activations[cast_time]) for cast_time in sorted(activations)
    ]
