"""Fiora's vital proc, on-hit Lunge and two-attack Bladework."""

from __future__ import annotations

from typing import Any

from .. import healing_helpers as _healing
from .engine import SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .inputs import bool_option, champion_stat, float_option, int_option
from .module_helpers import level_row, named_damage, no_damage, ranked_slot
from .slotlib import (
    ability_name,
    extract_named,
    proc_damage,
)
from .source_receipts import load_champion_sources

_vital_proc = proc_damage(
    level_row("Bonus Damage"),
    "true",
    count_option="p_vitals",
    default_count=0,
    name="Duelist's Dance vital",
    phase_order_events=True,
)


_lunge = named_damage(
    "Physical Damage",
    "physical",
    basic_damage=True,
    applies_item_on_hits={
        "effectiveness": 1.0,
        "hits": 1,
        "triggers": ("on_hit",),
    },
    # One stab on one target, no sourced travel phase — the certification
    # that carries Lunge's hit into the event ledger MODULE_CC is read from.
    event_order_certified="single_hit",
    detail="Lunge's stab applies one full-effectiveness on-hit package.",
)


_riposte = named_damage(
    "Magic Damage",
    "magic",
    time_offset=0.5,
    detail="Defensive stance/stun branch is retained as control state; the shock is one magic hit.",
)


@ranked_slot
def _bladework(
    ctx: SlotCtx, ability: dict[str, Any], _rank: int
) -> dict[str, Any] | None:
    attacks = min(max(int(ctx.option("e_attacks")), 1), 2)
    entry = no_damage(
        ctx,
        name=ability_name(ability),
        reason=(
            f"{attacks} empowered basic attack(s); first cannot crit and second uses "
            f"the sourced modified critical damage."
        ),
    )
    if entry is None:
        return None
    entry["empowers_next_auto"] = {"hits": attacks}
    entry["detail"] = (
        "Bladework's attack timer reset and slow are state-only; on-hit items ride the attacks."
    )
    return entry


def _grand_challenge(ctx: SlotCtx) -> dict[str, Any] | None:
    return no_damage(
        ctx,
        name="Grand Challenge",
        reason=(
            "Vital highlighting and Victory Zone healing are explicit challenge "
            "state, not outgoing damage."
        ),
    )


SLOTS = {
    "P": _vital_proc,
    "Q": _lunge,
    "W": _riposte,
    "E": _bladework,
    "R": _grand_challenge,
}
# Q only dashes and stabs.  W's shock: "the enemy champion struck is also
# slowed and crippled by 25% for 2 seconds" — the slow is the kind the cast
# lands on the target it damages (its stun branch needs Riposte to negate
# an immobilizing effect, which this module does not model).  R authors no
# damage part, and P's vitals are an effect-phase proc row whose event list
# the module builds itself, so a marker there would never reach the ledger.
#
# Bladework empowers two attacks and "the first attack slows the target
# by 30% for 1 second"; the row's damage is those swings, so the slow
# rides the events the engine reattributes to it.
MODULE_CC = {"Q": "none", "W": "slow", "E": "slow"}

parse_abilities = build_parser(SLOTS, "Fiora", cc_kinds=MODULE_CC)

OPTIONS = [
    int_option(
        "p_vitals", 0, minimum=0, maximum=4, label="Duelist's Dance vitals triggered"
    ),
    int_option("e_attacks", 2, minimum=1, maximum=2, label="Bladework attacks"),
    bool_option(
        "w_active", False, label="W (Riposte) active against selected incoming events"
    ),
    float_option(
        "w_active_from",
        0.0,
        minimum=0.0,
        maximum=120.0,
        label="W active start time in seconds",
    ),
    float_option(
        "w_active_seconds",
        0.0,
        minimum=0.0,
        maximum=0.75,
        label="W active seconds; zero uses the sourced 0.75 second duration",
    ),
    {
        "key": "w_blocked_sources",
        "type": "string_list",
        "default": [],
        "max_items": 24,
        "label": (
            "Incoming sources to negate; an empty list negates all matching events"
        ),
    },
]

ASSUMPTIONS = [
    "Vitals are explicit true-damage procs; the user supplies how many "
    "directional hits actually occur.",
    "Lunge is a real attack for item on-hit purposes, while Bladework's "
    "first/second crit distinction remains visible in its option detail.",
    "Grand Challenge's Victory Zone heals are not TDD and are not converted into damage.",
    "Riposte negates selected incoming damage and crowd control during the "
    "sourced 0.75 second stance; an empty source list means every incoming "
    "event in the window.",
]

SOURCES = load_champion_sources("Fiora")


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Resolve Fiora self-healing events from its authored packet."""
    healing = []
    p_level = int(champion_stat(champion_stats, "level"))
    p_heal = extract_named(
        _healing.ability_json(champion_data, "P"),
        "Bonus Damage",
        p_level,
        champion_stats,
    )
    for event in _healing.attributed_events(
        damage_events, lambda source, _event: source == "passive"
    ):
        _healing.heal_from_damage(healing, event, p_heal, "Duelist's Dance")
    return healing


SELF_HEALING_RULE = self_healing_rule("Fiora")(derive_self_healing)
