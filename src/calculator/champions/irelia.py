"""Irelia's max-stack on-hit, charge-scaled W and two-pass blade events."""

from __future__ import annotations

from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .engine import BUFF, SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .inputs import float_option, int_option
from .module_helpers import between_rows, named_damage, ranked_slot
from .slot_cc import CC_PER_PART
from .slot_entries import damage_entry, on_hit_entry
from .slot_extract import (
    ability_name,
    extract_cooldown,
    extract_named,
    find_named_leveling,
    sum_modifiers,
)
from .source_receipts import load_champion_sources

# ROOTED IN THE BINARY (data/bin/characters/irelia.bin.json): Ionian
# Fervor's stack cap and the seconds one stack lives are IreliaPassive's
# MaxStacks and BuffDuration.  A patch that moves a root moves the module.
_IRELIA_P_SPELL = spell_object("Irelia", "IreliaPassive")
_FERVOR_MAX_STACKS = int(data_value(_IRELIA_P_SPELL, "MaxStacks"))
_FERVOR_STACK_SECONDS = data_value(_IRELIA_P_SPELL, "BuffDuration")


def _p_row(ability: dict[str, Any], occurrence: int, ctx: SlotCtx) -> float:
    row = find_named_leveling(ability, "Per-Level Scaling", occurrence=occurrence)
    return sum_modifiers(row, ctx.level, ctx.stats, ctx.target) if row else 0.0


def _fervor(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    as_per_stack = _p_row(ability, 0, ctx)
    entry = on_hit_entry(ability_name(ability), 0.0, "magic")
    max_hit = {
        "name": "Ionian Fervor max-stack hit",
        "damage_per_hit": _p_row(ability, 2, ctx)
        + 0.20 * ctx.stat("bonus_attack_damage"),
        "damage_type": "magic",
    }
    requested = ctx.options.get("p_stacks")
    if requested is None:
        # A stack per ability hit, refreshed by basic attacks and ability
        # hits alike, so both streams stack it. The per-stack attack speed
        # re-rates the swings and the full count turns the max-stack on-hit
        # on, which is Volibear's pair of declarations.
        entry["swing_ramp"] = {
            "per_stack": as_per_stack / 100.0,
            "max_stacks": _FERVOR_MAX_STACKS,
            "stack_duration": _FERVOR_STACK_SECONDS,
            "stacks_from_swings": True,
            "stacks_from_ability_casts": True,
        }
        entry["armed_procs"] = {
            "arming_slots": (),
            "max_stacks": _FERVOR_MAX_STACKS,
            "hits_required": _FERVOR_MAX_STACKS,
            "stacks_from_swings": True,
            "stacks_from_ability_hits": True,
            "stack_seconds": _FERVOR_STACK_SECONDS,
            "retained_at_threshold": True,
            "armed_at_start": False,
            "requested": False,
        }
        entry["on_hit"] = max_hit
        entry["detail"] = (
            f"+{as_per_stack:g}% bonus attack speed per Ionian Fervor stack, up "
            f"to {_FERVOR_MAX_STACKS} held for {_FERVOR_STACK_SECONDS:g}s each; "
            "the fight walks the attacks and casts that stack them, and the "
            "max-stack on-hit is live for as long as the last stack is"
        )
        return entry
    stacks = min(max(int(requested), 0), _FERVOR_MAX_STACKS)
    bonus_as = as_per_stack * stacks
    entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    if stacks >= _FERVOR_MAX_STACKS:
        entry["on_hit"] = max_hit
    entry["detail"] = (
        f"{stacks} Ionian Fervor stack(s), +{bonus_as:g}% bonus attack speed; "
        f"max-stack on-hit is explicit."
    )
    return entry


_fervor.phase = BUFF


_bladesurge = named_damage(
    "Physical Damage",
    "physical",
    basic_damage=True,
    time_offset=0.2,
    applies_item_on_hits={
        "effectiveness": 1.0,
        "hits": 1,
        "triggers": ("on_hit",),
    },
    detail="One dash attack; reset, heal and Unsteady mark consumption are state branches.",
)


@ranked_slot
def _defiant_dance(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    charge = min(max(float(ctx.option("w_charge")), 0.0), 1.0)
    value = between_rows(
        ctx,
        ability,
        rank,
        "Minimum Physical Damage",
        high="Maximum Physical Damage",
        fraction=charge,
    )
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        value,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", value, time_offset=1.5 * charge),)
    entry["detail"] = (
        f"{charge:.2f} charge fraction; incoming physical/magic reduction is defensive state."
    )
    return entry


_flawless_duet = named_damage(
    "Magic Damage",
    "magic",
    time_offset=0.4,
)


@ranked_slot
def _vanguard(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    passes = min(max(int(ctx.option("r_passes")), 1), 2)
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        value * passes,
        "magic",
    )
    # One part per pass, at the times the single counted part already put
    # them (0.25 then 2.75), because the two passes control differently:
    # the barrage only damages and reveals — its blades "knock all enemy
    # units away ... though not rendering them airborne", which is not an
    # immobilize — while enemies crossing the perimeter "are slowed by 90%
    # for 1.5 seconds".
    parts = [DamagePart("magic", value, time_offset=0.25, cc_kind="none")]
    if passes > 1:
        parts.append(DamagePart("magic", value, time_offset=2.75, cc_kind="slow"))
    entry["parts"] = tuple(parts)
    entry["event_order_certified"] = "initial barrage and one perimeter pass"
    return entry


SLOTS = {
    "P": _fervor,
    "Q": _bladesurge,
    "W": _defiant_dance,
    "E": _flawless_duet,
    "R": _vanguard,
}
# Q dashes, heals and applies on-hit; W's recast swipe only damages; E's
# converging blades deal magic damage "and stun[] them for 0.75 seconds".
# R differs per pass, so its kinds ride its parts above.  P is the
# attack-speed/on-hit passive and authors no damage part.
MODULE_CC = {"Q": "none", "W": "none", "E": "stun", "R": CC_PER_PART, "P": "none"}

parse_abilities = build_parser(SLOTS, "Irelia", cc_kinds=MODULE_CC)
OPTIONS = [
    int_option(
        "p_stacks",
        _FERVOR_MAX_STACKS,
        minimum=0,
        maximum=_FERVOR_MAX_STACKS,
        label=(
            "Ionian Fervor stacks; unset walks the ramp, one stack per attack "
            "or ability hit, and arms the max-stack on-hit where it fills"
        ),
    ),
    float_option(
        "w_charge",
        1.0,
        minimum=0.0,
        maximum=1.0,
        label="Defiant Dance charge fraction",
        step=0.25,
    ),
    int_option("r_passes", 2, minimum=1, maximum=2, label="Vanguard's Edge passes"),
]
ASSUMPTIONS = [
    "Ionian Fervor's per-stack attack speed is applied before damage and its "
    "max-stack on-hit is explicit.",
    "Bladesurge is one full-effectiveness basic attack; Defiant Dance exposes the "
    "sourced charge interval.",
    "Vanguard's Edge models the initial barrage and one perimeter pass; marks, stun "
    "and slow are utility.",
]
SOURCES = load_champion_sources("Irelia")


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Resolve Irelia self-healing events from its authored packet."""
    healing = []
    ability = _healing.ability_json(champion_data, "Q")
    rank = _healing.parsed_rank(ability_damages, "Q")
    amount = extract_named(ability, "Heal", rank, champion_stats, {})
    for event in damage_events:
        if _healing.event_source(event) == "Q":
            _healing.heal_from_damage(healing, event, amount, "Bladesurge")
    return healing


SELF_HEALING_RULE = self_healing_rule("Irelia")(derive_self_healing)
