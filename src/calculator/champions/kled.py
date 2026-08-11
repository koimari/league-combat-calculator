"""Kled — full-entry reviewed CP10.3 module.

Option keys consumed by the shared parser: "q_pull", "charge_fraction".

Skaarl the Cowardly Lizard (P): while mounted, damage dealt to the duo
is suffered by Skaarl, whose 400 : 1400 (based on level) base health is
the mounted pool (data/champions.json P "Bonus Damage" leveling row).
The dismount/remount cycle is a revive-boundary pattern (like Aatrox's
ghost atom) and is NOT implemented: the E8a grey-health primitive
authors no Skaarl heal, and the pool is documented here as a boundary.
W (Violent Tendencies) is the 4-attack empowered burst; its fourth-hit
bonus is modeled by the CP10.3 packet.  Q (Pocket Pistol, the dismounted
Q) applies Grievous Wounds: the e8-interactions worklist
(data/worklists/e8-interactions.json) lists the Pocket Pistol GW, and
the wound rides the module's Q damage receipts at the patch-wide
40%-for-3s constants (healing_reduction module).
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import REVIEWED_MODULE_ASSUMPTIONS, no_damage, typed_damage
from .slotlib import (
    ability_on_hit_entry,
    extract_cooldown,
    extract_named,
    simple_damage,
)
from .source_receipts import load_champion_sources


def _bear_trap(ctx: SlotCtx) -> dict[str, Any] | None:
    attribute = (
        "Total Physical Damage"
        if bool(ctx.options.get("q_pull", True))
        else "Physical Damage"
    )
    return typed_damage(ctx, attribute, "physical")


def _violent_tendencies(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    value = extract_named(
        ability, "Additional Physical Damage", rank, ctx.stats, ctx.target
    )
    result = ability_on_hit_entry(
        ability.get("name", "Violent Tendencies"),
        rank,
        "physical",
        {
            "name": "Violent Tendencies (first three attacks)",
            "damage_per_hit": 0.0,
            "damage_type": "physical",
        },
        0.0,
    )
    result["parts"] = (
        DamagePart("physical", value, basic_damage=True, time_offset=0.1),
    )
    result["total_raw"] = value
    result["empowers_next_auto"] = True
    result["target_max_health_sensitive"] = True
    result["detail"] = (
        "Fourth attack of the four-hit Violent Tendencies sequence; 150% "
        "attack speed is state."
    )
    return result


def _charge(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    fraction = max(0.0, min(1.0, float(ctx.option("charge_fraction"))))
    low = extract_named(ability, "Minimum Magic Damage", rank, ctx.stats, ctx.target)
    high = extract_named(ability, "Maximum Magic Damage", rank, ctx.stats, ctx.target)
    value = low + (high - low) * fraction
    return {
        "name": ability.get("name", "Chaaaaaaaarge!!!"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": value,
        "parts": (DamagePart("magic", value, time_offset=0.5),),
        "target_max_health_sensitive": True,
        "detail": (
            f"Charge fraction {fraction:.2f}; shield and team movement are "
            "utility state."
        ),
    }


SLOTS = {
    "P": lambda ctx: no_damage(
        ctx,
        name="Skaarl the Cowardly Lizard",
        reason=(
            "Mounted/dismounted health pool, remount and damage cutoff are "
            "participant state."
        ),
    ),
    "Q": _bear_trap,
    "W": _violent_tendencies,
    "E": simple_damage(attr="Total Physical Damage", dmg_type="physical"),
    "R": _charge,
}
OPTIONS = [
    {
        "key": "q_pull",
        "type": "bool",
        "default": True,
        "label": "Bear Trap pull resolves",
    },
    {
        "key": "charge_fraction",
        "type": "float",
        "default": 1.0,
        "min": 0.0,
        "max": 1.0,
        "step": 0.25,
        "label": "Chaaaaaaaarge distance",
    },
]
ASSUMPTIONS = list(REVIEWED_MODULE_ASSUMPTIONS)
SOURCES = load_champion_sources("Kled")
parse_abilities = build_parser(SLOTS, "Kled")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "Skaarl the Cowardly Lizard (P): the mounted duo's damage is suffered "
    "by Skaarl, whose 400 : 1400 (based on level) base health is the "
    "mounted pool (data/champions.json P 'Bonus Damage'); the "
    "dismount/remount cycle is a revive-boundary pattern (like Aatrox's "
    "ghost atom) and is not modeled — the E8a grey-health primitive "
    "authors no Skaarl heal.",
    "Q Grievous Wounds: REMOVED — Pocket Pistol's wound was deleted in "
    "V25.14 (the e8-interactions worklist entry is stale; the wiki cache "
    "carries no Grievous Wounds on either Q entry), so the module declares "
    "no wound source.",
]

# HARDCODED: verify on patch updates.  Kled's Grievous Wounds (historically
# on the Bear Trap on a Rope pull) was REMOVED in V25.14 — the e8-interactions
# worklist entry is stale and the wiki cache carries no wound on either Q
# entry (autoresearch pass 11, 2026-08-07).  Empty declaration = no wound.
GRIEVOUS_WOUNDS_SOURCES = frozenset()
GRIEVOUS_WOUNDS_SOURCE_LABELS = {}

MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "no_damage")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
