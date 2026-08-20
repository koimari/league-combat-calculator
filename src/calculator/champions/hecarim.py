"""Hecarim's movement-scaled AD, Rampage stacks and authored hit cadence."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, extract_named, extract_value
from .source_receipts import load_champion_sources


def _warpath(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    percent = extract_value(ability, "Per-Level Scaling", ctx.level)
    bonus_ms = float(ctx.option("bonus_movement_speed"))
    if bonus_ms <= 0.0:
        bonus_ms = max(0.0, float(ctx.stat("move_speed")) - 325.0)
    bonus_ad = percent * bonus_ms / 100.0
    ctx.stats["bonus_attack_damage"] = ctx.stat("bonus_attack_damage") + bonus_ad
    ctx.stats["attack_damage"] = ctx.stat("attack_damage") + bonus_ad
    entry = damage_entry(
        ability.get("name", "Warpath"), ctx.level, 0.0, 0.0, "physical"
    )
    entry["stat_buff"] = {"bonus_attack_damage": bonus_ad}
    entry["detail"] = (
        f"{percent:g}% of {bonus_ms:g} bonus movement speed grants {bonus_ad:g} bonus AD."
    )
    return entry


_warpath.phase = BUFF


def _rampage(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    stacks = min(max(int(ctx.option("q_stacks")), 0), 3)
    base = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    multiplier = 1.0 + stacks * (0.03 + 0.03 * ctx.stat("bonus_attack_damage") / 100.0)
    value = base * multiplier
    return {
        "name": ability.get("name", "Rampage"),
        "rank": rank,
        "cooldown": max(0.0, extract_cooldown(ability, rank) - 0.75 * stacks),
        "damage_type": "physical",
        "total_raw": value,
        "parts": (DamagePart("physical", value, time_offset=0.1),),
        "detail": f"{stacks} Rampage stack(s); damage multiplier {multiplier:.3f}.",
    }


# W (Spirit of Dread) ticks once per second for 5 seconds — the JSON's
# "Total Magic Damage" row is exactly 5x the "Magic Damage Per Tick"
# row at every rank (100/20 .. 300/60), so the tick count is sourced
# rather than invented.
_W_TICKS = 5


def _spirit_of_dread(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    ticks = min(max(int(ctx.options.get("w_ticks", _W_TICKS)), 1), _W_TICKS)
    per_tick = extract_named(
        ability, "Magic Damage Per Tick", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability.get("name", "Spirit of Dread"),
        rank,
        extract_cooldown(ability, rank),
        per_tick * ticks,
        "magic",
    )
    entry["parts"] = (
        DamagePart("magic", per_tick, count=ticks, time_offset=0.0, hit_interval=1.0),
    )
    entry["detail"] = (
        "One sourced area tick per second; healing and bonus resistances remain state in the ledger."
    )
    return entry


def _devastating_charge(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    distance = min(max(float(ctx.option("e_charge")), 0.0), 1.0)
    low = extract_named(ability, "Minimum Physical Damage", rank, ctx.stats, ctx.target)
    high = extract_named(
        ability, "Maximum Physical Damage", rank, ctx.stats, ctx.target
    )
    value = low + (high - low) * distance
    entry = damage_entry(
        ability.get("name", "Devastating Charge"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "physical",
    )
    entry["parts"] = (
        DamagePart("physical", value, basic_damage=True, time_offset=0.25),
    )
    entry["empowers_next_auto"] = True
    entry["applies_item_on_hits"] = {
        "effectiveness": 1.0,
        "hits": 1,
        "triggers": ("on_hit",),
    }
    entry["detail"] = (
        f"Distance fraction {distance:.2f}; the next basic attack is empowered and knocks back."
    )
    return entry


SLOTS = {
    "P": _warpath,
    "Q": _rampage,
    "W": _spirit_of_dread,
    "E": _devastating_charge,
    "R": lambda ctx: _r(ctx),
}


def _r(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    return damage_entry(
        ability.get("name", "Onslaught of Shadows"),
        rank,
        extract_cooldown(ability, rank),
        extract_named(ability, "Magic damage", rank, ctx.stats, ctx.target),
        "magic",
        event_order_certified="single_hit",
    )


# Q's cleave and W's aura only damage.  E's charge "knocks them back ...
# stuns them for 0.25 seconds" — the first-listed immobilize is the
# knockback.  R's riders damage on the way through and Hecarim then "fears
# nearby enemies" on arrival.  P is the bonus-AD conversion row and applies
# nothing.
MODULE_CC = {"Q": "none", "W": "none", "E": "knockback", "R": "fear"}

parse_abilities = build_parser(SLOTS, "Hecarim", cc_kinds=MODULE_CC)
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
        "key": "q_stacks",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 3,
        "label": "Rampage stacks",
    },
    {
        "key": "w_ticks",
        "type": "int",
        "default": _W_TICKS,
        "min": 1,
        "max": _W_TICKS,
        "label": "Spirit of Dread ticks",
    },
    {
        "key": "e_charge",
        "type": "float",
        "default": 1.0,
        "min": 0.0,
        "max": 1.0,
        "step": 0.25,
        "label": "Devastating Charge distance fraction",
    },
]
ASSUMPTIONS = [
    "Warpath reads the explicit bonus-movement-speed input and updates bonus AD before later casts.",
    "Rampage stacks and Spirit of Dread ticks are explicit ordered state; ally healing, fear and displacement are utility.",
    "Devastating Charge is one empowered basic attack and therefore shares the item/on-hit timeline.",
]
SOURCES = load_champion_sources("Hecarim")

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Hecarim")
