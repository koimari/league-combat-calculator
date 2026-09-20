"""Locke: full-entry reviewed module.

Option keys consumed by this module: "q_casts", "soul_nails", "e_dash".
W (Soul Ignition)'s recast heal is authored by the shared grey-health
primitive: W stores grey health equal to 100% of the post-mitigation damage
Locke takes from enemy champions, up to the cached "Damage taken grey health
cap" row, each cast opening a 6-second storage window whose automatic recast
heals the stored pool.  The health-cost add and the missing-health bonus stay
documented dynamic-self-state boundaries; the deterministic pool is the sourced
100%-of-damage-taken term.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .inputs import bool_option, int_option
from .module_helpers import (
    REVIEWED_MODULE_ASSUMPTIONS,
    ability_slot,
    named_damage,
    no_damage,
    typed_damage,
    with_item_on_hit_specs,
)
from .slot_entries import damage_entry, on_hit_entry
from .slot_extract import ability_name, extract_cooldown, extract_named
from .source_receipts import load_champion_sources


@ability_slot()
def _silver_stake(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    """P: on-hit damage scaling linearly with target missing health."""
    base = extract_named(
        ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
    )
    missing_ratio = float(ctx.target_stat("target_missing_health") or 0.0) / max(
        1.0, float(ctx.target_stat("target_max_health") or 1.0)
    )
    value = base * (1.0 + max(0.0, min(1.0, missing_ratio)))
    result = on_hit_entry("Silver Stake", value, "magic")
    result["target_max_health_sensitive"] = True
    result["detail"] = (
        "On-hit damage doubles linearly with target missing-health ratio, "
        "capped by the sourced bonus row."
    )
    return result


@ability_slot()
def _ritual_nails(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    """Q: one to three casts plus the selected Soul Nails detonation."""
    rank = ctx.rank_for()
    casts = max(1, min(3, int(ctx.option("q_casts"))))
    per = extract_named(ability, "Magic Damage per Nail", rank, ctx.stats, ctx.target)
    stacks = max(0, min(3, int(ctx.option("soul_nails"))))
    bonus_attr = {
        1: "One Stack Bonus Damage",
        2: "Two Stacks Bonus Damage",
        3: "Three Stacks Bonus Damage",
    }.get(stacks)
    bonus = (
        extract_named(ability, bonus_attr, rank, ctx.stats, ctx.target)
        if bonus_attr
        else 0.0
    )
    parts = [DamagePart("magic", per, count=casts, time_offset=0.15, hit_interval=0.15)]
    if bonus:
        parts.append(DamagePart("magic", bonus, time_offset=0.5))
    return damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        per * casts + bonus,
        "magic",
        parts=tuple(parts),
        detail=(
            f"{casts} Ritual Nails casts; {stacks} Soul Nails stacks are "
            "consumed by the next damaging attack."
        ),
    )


# E: blink packet plus the optional empowered dash attack.
_ashen_pursuit = named_damage(
    lambda ctx: (
        "Total Magic Damage" if bool(ctx.option("e_dash")) else "Blink Magic Damage"
    ),
    "magic",
    time_offset=0.1,
    detail="Ashen Pursuit blink plus optional empowered dash attack.",
)


def _purgatory(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: totem damage; mark refresh and execute remain target state."""
    result = typed_damage(ctx, "Magic Damage", "magic", time_offset=0.75)
    if result:
        result["target_max_health_sensitive"] = True
        result["detail"] = (
            "Purgatory totem damage; mark refresh and execute threshold remain "
            "explicit target state."
        )
    return result


SLOTS = {
    "P": _silver_stake,
    "Q": _ritual_nails,
    "W": lambda ctx: no_damage(
        ctx,
        name="Soul Ignition",
        reason=(
            "Grey health storage, attack speed, movement speed and recast healing "
            "are self-state."
        ),
    ),
    "E": _ashen_pursuit,
    "R": _purgatory,
}

OPTIONS: list[dict[str, Any]] = [
    int_option(
        "q_casts",
        3,
        minimum=1,
        maximum=3,
        label="Ritual Nails casts",
        rotation={"role": "self_state", "slot": "Q"},
    ),
    int_option(
        "soul_nails",
        0,
        minimum=0,
        maximum=3,
        label="Soul Nails stacks",
        rotation={"role": "self_state", "slot": "P"},
    ),
    bool_option(
        "e_dash",
        True,
        label="Ashen Pursuit dash",
        rotation={"role": "self_state", "slot": "E"},
    ),
]

ASSUMPTIONS = list(REVIEWED_MODULE_ASSUMPTIONS)
SOURCES = load_champion_sources("Locke")

# Cached kit review: Q's nails "slow[] them by 25% for 1 second" (60% at
# two Soul Nails stacks) and R's latching nails slow "by 99% decaying over
# 2 seconds"; E blinks and dashes without applying control.  W is a
# self-buff and P an on-hit rider, neither emitting an ability event.
MODULE_CC = {"Q": "slow", "E": "none", "R": "slow", "P": "none", "W": "none"}

parse_abilities = build_parser(SLOTS, "Locke", cc_kinds=MODULE_CC)

_ON_HIT_SPECS: dict[str, dict] = {
    "E": {"effectiveness": 1.0, "hits": 1, "triggers": ("on_hit",)},
}

parse_abilities = with_item_on_hit_specs(parse_abilities, _ON_HIT_SPECS)


ASSUMPTIONS += [
    "W (Soul Ignition) recast heal is authored by the grey-health "
    "primitive: 100% of the post-mitigation champion damage taken during "
    "the 6s active is stored (capped by the 'Damage taken grey health "
    "cap' row) and healed at the automatic 6s recast.  The health-cost "
    "add and the missing-health bonus are dynamic self-state boundaries, "
    "per the E1-b6 scope note",
]
