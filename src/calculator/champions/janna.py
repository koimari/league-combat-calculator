"""Janna's charge-scaled whirlwind, Zephyr damage and utility branches.

E8d ally-support: E (Eye of the Storm, Shield Strength 80-240 + 55% AP, scope
one_teammate) shields the selected teammate; R (Monsoon, Total Heal 300-600 +
150% AP, scope self_and_all_teammates) heals the caster and all allies.  Both
events are authored by the engine's ally-support scanner from cached leveling
at the cast times; the module declares E/R in SLOTS so the fight rotation
casts them.  R's heal is delivered as the sourced Total Heal at cast time
(the cached per-tick row is the cadence detail: 12 ticks x Heal Per Tick ==
Total Heal).
"""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import no_damage, source_row
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    on_hit_entry,
)


def _tailwind(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    bonus_ms = max(0.0, float(ctx.option("bonus_movement_speed")))
    value = 0.30 * bonus_ms
    entry = on_hit_entry(ability.get("name", "Tailwind"), value, "magic")
    entry["detail"] = (
        f"30% of the explicit {bonus_ms:g} bonus movement speed is bonus magic damage on attacks and Zephyr."
    )
    return entry


def _howling_gale(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    charge = min(max(float(ctx.option("q_charge")), 0.0), 1.0)
    low = extract_named(ability, "Minimum Magic Damage", rank, ctx.stats, ctx.target)
    high = extract_named(ability, "Maximum Magic Damage", rank, ctx.stats, ctx.target)
    value = low + (high - low) * charge
    entry = damage_entry(
        ability.get("name", "Howling Gale"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=1.25),)
    entry["detail"] = (
        f"{charge:.2f} charge fraction; knock-up and recast direction are utility state."
    )
    return entry


def _zephyr(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Zephyr"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value),)
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = (
        "Passive movement speed and active slow are sourced utility; the active is one magic hit."
    )
    return entry


SLOTS = {
    "P": _tailwind,
    "Q": _howling_gale,
    "W": _zephyr,
    "E": lambda ctx: no_damage(
        ctx,
        name="Eye of the Storm",
        reason="Shield and bonus attack damage are ally-facing defensive utility.",
    ),
    "R": lambda ctx: no_damage(
        ctx,
        name="Monsoon",
        reason="Knockback and channelled healing are utility; the parent entry has no outgoing champion damage formula.",
    ),
}
# Q's whirlwind deals magic damage "and knock[s] them up"; W's air
# elemental "deals magic damage and slows them for 2 seconds".  P is the
# on-hit bonus row and E/R author no damage part at all (Monsoon's
# knockback has no damage formula in the cached entry).
MODULE_CC = {"Q": "knockup", "W": "slow"}

parse_abilities = build_parser(SLOTS, "Janna", cc_kinds=MODULE_CC)
OPTIONS = [
    {
        "key": "bonus_movement_speed",
        "type": "float",
        "default": 0.0,
        "min": 0.0,
        "max": 500.0,
        "label": "Bonus movement speed",
    },
    {
        "key": "q_charge",
        "type": "float",
        "default": 1.0,
        "min": 0.0,
        "max": 1.0,
        "step": 0.25,
        "label": "Howling Gale charge fraction",
    },
]
ASSUMPTIONS = [
    "Tailwind's 30% bonus-movement-speed on-hit uses the explicit movement-speed input.",
    "Howling Gale interpolates the sourced minimum/maximum charge packet; W's passive movement speed is not double-counted as damage.",
    "Eye of the Storm and Monsoon are visible ally/defensive utility, not TDD.",
]
SOURCES = [
    source_row(
        "Janna parent entry",
        "https://wiki.leagueoflegends.com/en-us/Janna",
        3892602,
        "2025-05-02T11:23:59Z",
    ),
    source_row(
        "Janna Q template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Janna/Q",
        2863952,
        "2019-11-03T19:57:09Z",
    ),
    source_row(
        "Janna W template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Janna/W",
        2864247,
        "2019-11-03T20:09:56Z",
    ),
    source_row(
        "Janna E template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Janna/E",
        2864393,
        "2019-11-03T20:12:27Z",
    ),
    source_row(
        "Janna R template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Janna/R",
        2864539,
        "2019-11-03T20:15:51Z",
    ),
]

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Janna")
