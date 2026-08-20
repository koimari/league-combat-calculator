"""Jax's stackable attack speed, empowered attack, Counter Strike and R state."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .module_helpers import no_damage, source_row
from .slotlib import (
    ability_on_hit_entry,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    sum_modifiers,
    simple_damage,
)


def _assault(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    stacks = min(max(int(ctx.option("p_stacks")), 0), 8)
    row = find_named_leveling(ability, "Per-Level Scaling")
    per_stack = sum_modifiers(row, ctx.level, ctx.stats, ctx.target) if row else 0.0
    bonus_as = per_stack * stacks
    entry = no_damage(
        ctx,
        name=ability.get("name", "Relentless Assault"),
        reason=f"{stacks} attack-speed stacks; fish/river economy is explicit utility.",
    )
    if entry is not None:
        entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    return entry


_assault.phase = BUFF


def _empower(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(
        ability, "Additional Magic Damage", rank, ctx.stats, ctx.target
    )
    entry = ability_on_hit_entry(
        ability.get("name", "Empower"),
        rank,
        "magic",
        {"name": "Empower", "damage_per_hit": value, "damage_type": "magic"},
        extract_cooldown(ability, rank),
    )
    entry["empowers_next_auto"] = True
    entry["detail"] = (
        "Empowers one basic attack or Leap Strike and resets the attack timer."
    )
    return entry


def _counter_strike(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    dodged = min(max(int(ctx.option("e_dodged_attacks")), 0), 5)
    low = extract_named(ability, "Minimum Magic Damage", rank, ctx.stats, ctx.target)
    high = extract_named(ability, "Maximum Magic Damage", rank, ctx.stats, ctx.target)
    value = low + (high - low) * dodged / 5.0
    entry = damage_entry(
        ability.get("name", "Counter Strike"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=2.0),)
    entry["detail"] = (
        f"{dodged} dodged attacks; evasion and area-damage reduction are defensive state."
    )
    return entry


def _grandmaster(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Grandmaster-at-Arms"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=0.4),)
    armor = (
        extract_value(ability, "Bonus Armor", rank)
        + extract_value(ability, "Bonus Armor", rank, 1)
        * ctx.stat("bonus_attack_damage")
        / 100.0
    )
    mr = (
        extract_value(ability, "Bonus Magic Resistance", rank)
        + extract_value(ability, "Bonus Magic Resistance", rank, 1)
        * ctx.stat("bonus_attack_damage")
        / 100.0
    )
    entry["stat_buff"] = {"bonus_armor": armor, "bonus_magic_resistance": mr}
    if bool(ctx.options.get("r_passive_ready", False)):
        proc = extract_named(
            ability, "Additional Magic Damage", rank, ctx.stats, ctx.target
        )
        entry["on_hit"] = {
            "name": "Grandmaster-at-Arms passive",
            "damage_per_hit": proc,
            "damage_type": "magic",
        }
    entry["detail"] = (
        f"Active lantern swing; +{armor:g} armor/+{mr:g} magic resistance for the authored 8-second window."
    )
    return entry


SLOTS = {
    "P": _assault,
    "Q": simple_damage(
        attr="Physical Damage",
        dmg_type="physical",
        event_order_certified="single_hit",
    ),
    "W": _empower,
    "E": _counter_strike,
    "R": _grandmaster,
}

# Q's leap only damages the target it lands on and R's lantern swing only
# damages.  E's recast "deals magic damage to nearby enemies ... and stuns
# them for 1 second".  P is the attack-speed stack row and authors no
# damage part.
#
# W (Empower) empowers "his next basic attack or Leap Strike ... to deal
# additional magic damage" and nothing else — a reviewed absence of
# control, riding the swing the cast forces.
MODULE_CC = {"Q": "none", "W": "none", "R": "none", "E": "stun"}

parse_abilities = build_parser(SLOTS, "Jax", cc_kinds=MODULE_CC)
OPTIONS = [
    {
        "key": "p_stacks",
        "type": "int",
        "default": 8,
        "min": 0,
        "max": 8,
        "label": "Relentless Assault stacks",
    },
    {
        "key": "e_dodged_attacks",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 5,
        "label": "Counter Strike attacks dodged",
    },
    {
        "key": "r_passive_ready",
        "type": "bool",
        "default": False,
        "label": "Grandmaster passive hit ready",
    },
]
ASSUMPTIONS = [
    "Relentless Assault is an explicit stack-derived attack-speed buff; it is applied before later casts and autos.",
    "Empower is one next-attack magic rider; Counter Strike uses the sourced 0–100% dodge-damage range.",
    "Grandmaster-at-Arms includes the active swing and defensive resistances; its passive hit is opt-in to avoid inventing prior stacks.",
]
SOURCES = [
    source_row(
        "Jax parent entry",
        "https://wiki.leagueoflegends.com/en-us/Jax",
        3979077,
        "2025-12-25T10:27:57Z",
    ),
    source_row(
        "Jax Q template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Jax/Q",
        2863954,
        "2019-11-03T19:57:11Z",
    ),
    source_row(
        "Jax W template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Jax/W",
        2864249,
        "2019-11-03T20:09:58Z",
    ),
    source_row(
        "Jax E template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Jax/E",
        2864395,
        "2019-11-03T20:12:29Z",
    ),
    source_row(
        "Jax R template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Jax/R",
        3909966,
        "2025-06-11T21:00:25Z",
    ),
]
