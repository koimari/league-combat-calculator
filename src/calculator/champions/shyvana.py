"""Shyvana's human/dragon combat states and timed packets."""

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    simple_damage,
    sum_modifiers,
)


def _scalemail(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("P")
    if ability is None:
        return None
    base = find_named_leveling(ability, "Per-Level Scaling", 0)
    stack = find_named_leveling(ability, "Per-Level Scaling", 1)
    if base is None or stack is None:
        return None
    stacks = min(max(int(ctx.options.get("scalemail_stacks", 0)), 0), 100)
    bonus_armor = sum_modifiers(base, ctx.level) + stacks * sum_modifiers(
        stack, ctx.level
    )
    ctx.stats["armor"] = ctx.stats.get("armor", 0.0) + bonus_armor
    ctx.stats["magic_resistance"] = ctx.stats.get("magic_resistance", 0.0) + bonus_armor
    entry = damage_entry("Scalemail", ctx.level, 0.0, 0.0, "physical")
    entry["stat_buff"] = {"armor": bonus_armor, "magic_resistance": bonus_armor}
    entry["detail"] = f"{stacks} Scalemail stack(s); +{bonus_armor:.2f} armor/MR"
    return entry


_scalemail.phase = BUFF


def _emberstrike(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("Q")
    if ability is None:
        return None
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None
    casts = min(max(int(ctx.options.get("q_casts", 1)), 1), 3)
    dragon = bool(ctx.options.get("dragon_form", False))
    human = extract_named(ability, "Area Physical Damage", rank, ctx.stats, ctx.target)
    dragon_third = extract_named(ability, "True Damage", rank, ctx.stats, ctx.target)
    parts: list[DamagePart] = []
    for index in range(casts):
        amount = dragon_third if dragon and index == 2 else human
        dtype = "true" if dragon and index == 2 else "physical"
        parts.append(DamagePart(dtype, amount, time_offset=0.0, hit_interval=0.0))
    total = sum(part.amount for part in parts)
    entry = damage_entry(
        ability.get("name", "Emberstrike"),
        rank,
        extract_cooldown(ability, rank),
        total,
        (
            "mixed"
            if len({part.damage_type for part in parts}) > 1
            else parts[0].damage_type
        ),
    )
    entry["parts"] = tuple(parts)
    entry["detail"] = (
        f"{casts} Emberstrike cast(s), {'dragon' if dragon else 'human'} form"
    )
    entry["empowers_next_auto"] = True
    return entry


def _inferno_aegis(ctx: SlotCtx) -> dict[str, Any] | None:
    if not bool(ctx.options.get("w_recast", True)):
        return None
    ability = ctx.ability("W")
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    total = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        "Inferno Aegis (recast)", rank, extract_cooldown(ability, rank), total, "magic"
    )
    entry["parts"] = (DamagePart("magic", total, time_offset=1.0),)
    entry["detail"] = "shield consumed after the sourced one-second recast window"
    return entry


def _molten_burst(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("E")
    if ability is None:
        return None
    rank = ctx.rank_for("E")
    dragon = bool(ctx.options.get("dragon_form", False))
    attr = "Increased/Explosion Magic Damage" if dragon else "Magic Damage"
    total = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    parts = [DamagePart("magic", total, time_offset=0.0)]
    if dragon and bool(ctx.options.get("e_second_explosion", False)):
        second = extract_named(
            ability, "Subsequent Explosion Damage", rank, ctx.stats, ctx.target
        )
        parts.append(DamagePart("magic", second, time_offset=0.0))
        total += second
    entry = damage_entry(
        ability.get("name", "Molten Burst"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = tuple(parts)
    entry["detail"] = "dragon-form explosion" if dragon else "human-form fireball"
    return entry


SLOTS = {
    "P": _scalemail,
    "Q": _emberstrike,
    "W": _inferno_aegis,
    "E": _molten_burst,
    "R": simple_damage(attr="Magic Damage", dmg_type="magic"),
}

parse_abilities = build_parser(SLOTS, "Shyvana")

OPTIONS = [
    {
        "key": "scalemail_stacks",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 100,
        "label": "Scalemail stacks",
    },
    {"key": "dragon_form", "type": "bool", "default": False, "label": "Dragon Form"},
    {
        "key": "q_casts",
        "type": "int",
        "default": 1,
        "min": 1,
        "max": 3,
        "label": "Emberstrike casts",
    },
    {
        "key": "w_recast",
        "type": "bool",
        "default": True,
        "label": "Inferno Aegis recast hits",
    },
    {
        "key": "e_second_explosion",
        "type": "bool",
        "default": False,
        "label": "Dragon E second explosion",
    },
]

ASSUMPTIONS = [
    "Scalemail armor and magic resistance use explicit stack state; the passive has no direct damage.",
    "Inferno Aegis defaults to its one-second recast damage; the shield and movement utility remain visible as an assumption.",
    "Dragon-form Q/E variants and the second explosion are explicit options, never inferred from a cast count.",
]

SOURCES = [
    {
        "label": "Shyvana — full champion entry",
        "url": "https://wiki.leagueoflegends.com/en-us/Shyvana",
        "revision_id": 4043672,
        "revision_timestamp": "2026-07-15T18:06:00Z",
    }
]
