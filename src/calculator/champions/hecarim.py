"""Hecarim's movement-scaled AD, Rampage stacks and authored hit cadence."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .reviewed_batch_01 import source_row
from .slotlib import damage_entry, extract_cooldown, extract_named, extract_value


def _warpath(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    percent = extract_value(ability, "Per-Level Scaling", ctx.level)
    bonus_ms = float(ctx.options.get("bonus_movement_speed", 0.0))
    if bonus_ms <= 0.0:
        bonus_ms = max(0.0, float(ctx.stats.get("move_speed", 325.0)) - 325.0)
    bonus_ad = percent * bonus_ms / 100.0
    ctx.stats["bonus_attack_damage"] = (
        ctx.stats.get("bonus_attack_damage", 0.0) + bonus_ad
    )
    ctx.stats["attack_damage"] = ctx.stats.get("attack_damage", 0.0) + bonus_ad
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
    stacks = min(max(int(ctx.options.get("q_stacks", 0)), 0), 3)
    base = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    multiplier = 1.0 + stacks * (
        0.03 + 0.03 * ctx.stats.get("bonus_attack_damage", 0.0) / 100.0
    )
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


def _spirit_of_dread(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    ticks = min(max(int(ctx.options.get("w_ticks", 4)), 1), 4)
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
    distance = min(max(float(ctx.options.get("e_charge", 1.0)), 0.0), 1.0)
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
    )


parse_abilities = build_parser(SLOTS, "Hecarim")
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
        "default": 4,
        "min": 1,
        "max": 4,
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
SOURCES = [
    source_row(
        "Hecarim parent entry",
        "https://wiki.leagueoflegends.com/en-us/Hecarim",
        3957268,
        "2025-10-04T15:12:42Z",
    ),
    source_row(
        "Hecarim Q template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Hecarim/Q",
        2863947,
        "2019-11-03T19:57:04Z",
    ),
    source_row(
        "Hecarim W template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Hecarim/W",
        2864242,
        "2019-11-03T20:09:51Z",
    ),
    source_row(
        "Hecarim E template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Hecarim/E",
        2864388,
        "2019-11-03T20:12:22Z",
    ),
    source_row(
        "Hecarim R template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Hecarim/R",
        2864534,
        "2019-11-03T20:15:46Z",
    ),
]
MODULE_COVERAGE = {slot: "modeled" for slot in ("P", "Q", "W", "E", "R")}
REVIEW_STATUS = "reviewed_module"
