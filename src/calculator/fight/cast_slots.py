"""The cast-slot vocabulary: which slot a row belongs to, and which casts did damage."""

from collections.abc import Mapping
from typing import Any

from ..ability_atoms import ability_field, ability_payload
from ..champions.cast_arming import banking_swings, declared_rules, ready_at
from .results import RotationResult
from .state import FightState

# Default ability cast order when a fight doesn't specify one. Q2 is
# skipped harmlessly for champions without a second Q cast. A tuple so a
# fight can never mutate the shared default; use sites materialize a list.
DEFAULT_CAST_ORDER = ("Q", "Q2", "W", "E", "R")


# A row keyed to no slot at all (``passive``) resolves to itself, which is
# never one of Q/W/E/R — the test every caller makes.
def _base_slot(key: str) -> str:
    """The cast slot an ability row belongs to (``Q2``/``W_frenzy`` -> ``Q``/``W``)."""
    return key.split("_", 1)[0].rstrip("0123456789")


# Two things are live without a cast of their own: a passive row
# (``passive``, ``passive_plasma``), and an active row whose payload the module
# declares ``innate_grant`` — an always-on passive that happens to hang off an
# active slot (Darius E's armor penetration, Kog'Maw Q's, Nocturne W's, Quinn
# W's).  Everything else is bought with a cast, so autos-only
# (``casts_nothing``) earns none of it, including a cast-derived
# ``off_rotation_grant`` whose window average counts casts the rotation omits
# (Kai'Sa E).  Outside that mode an ``off_rotation_grant`` is live, and any
# other active row is live when its key, or the base slot of its variant key
# (``Q2`` -> ``Q``), is in the cast order; an unknown order casts every slot.
def _slot_is_cast(
    key: str,
    info: Mapping[str, Any],
    cast_order: "list[str] | None",
    casts_nothing: bool = False,
) -> bool:
    """Whether the ability row *key* carries a payload this fight earns."""
    base = _base_slot(key)
    if base not in ("Q", "W", "E", "R") or info.get("innate_grant"):
        return True
    if casts_nothing:
        return False
    if info.get("off_rotation_grant") or cast_order is None:
        return True
    return key in cast_order or base in cast_order


def slot_cast_start(state: FightState, key: str) -> float:
    """When the row *key*'s first cast lands: the cast times of the slots ordered before it.

    A row keyed to no slot in the cast order (a passive, an innate grant
    hanging off an active) is live from the fight open, so its start is 0.
    """
    base = _base_slot(key)
    cast_start = 0.0
    for slot in state.cast_order:
        if slot in (key, base):
            return max(cast_start, _armed_at(state, key, base))
        cast_start += float(
            ability_field(ability_payload(state.ability_damages, slot), "cast_time")
        )
    return 0.0


def _armed_at(state: FightState, key: str, base: str) -> float:
    """When a slot gated on a counter the fight banks may first cast.

    Zero for every slot that declares no gate, which is all but Ashe's
    Ranger's Focus. A gate the fight never fills answers at the fight's own
    end, so the window the caller opens holds no swing: an unreachable
    instant is not a number the rest of the engine can carry.
    """
    rules = declared_rules(state.ability_damages)
    rule = rules.get(key) or rules.get(base)
    if rule is None:
        return 0.0
    armed = ready_at(
        rule,
        banking_swings(
            state.attack_speed,
            state.auto_attack_uptime,
            state.fight_duration_seconds,
        ),
    )
    return min(armed, state.fight_duration_seconds)


def _damaging_cast_times(state: FightState, rotation: RotationResult) -> list[float]:
    """Chronological cast times of accepted DAMAGING ability casts.

    Zero-damage casts (stat-buff ultimates) are excluded — they apply no
    keystone stacks and hurl no comets. Instances the engine cannot
    timestamp or certify are not counted — item-effect applications,
    recast instances beyond the first, and pure crowd-control casts (CC
    application stacks in game, but the engine carries no CC metadata).
    Omitting an instance can only delay a proc, never invent one.
    """
    damaging_slots = {
        slot
        for slot, entry in state.ability_damages.items()
        if float(entry.get("total_raw", 0.0)) > 0
    }
    return sorted(
        float(event["time"])
        for event in rotation.cast_events
        if event.get("slot") in damaging_slots
    )
