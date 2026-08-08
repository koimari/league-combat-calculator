"""Irelia's max-stack on-hit, charge-scaled W and two-pass blade events."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .module_helpers import source_row
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    find_named_leveling,
    on_hit_entry,
    sum_modifiers,
)


def _p_row(ability: dict[str, Any], occurrence: int, ctx: SlotCtx) -> float:
    row = find_named_leveling(ability, "Per-Level Scaling", occurrence=occurrence)
    return sum_modifiers(row, ctx.level, ctx.stats, ctx.target) if row else 0.0


def _fervor(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    stacks = min(max(int(ctx.options.get("p_stacks", 4)), 0), 4)
    as_per_stack = _p_row(ability, 0, ctx)
    bonus_as = as_per_stack * stacks
    entry = on_hit_entry(ability.get("name", "Ionian Fervor"), 0.0, "magic")
    entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    if stacks >= 4:
        damage = _p_row(ability, 2, ctx) + 0.20 * ctx.stats.get(
            "bonus_attack_damage", 0.0
        )
        entry["on_hit"] = {
            "name": "Ionian Fervor max-stack hit",
            "damage_per_hit": damage,
            "damage_type": "magic",
        }
    entry["detail"] = (
        f"{stacks} Ionian Fervor stack(s), +{bonus_as:g}% bonus attack speed; max-stack on-hit is explicit."
    )
    return entry


_fervor.phase = BUFF


def _bladesurge(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Bladesurge"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "physical",
    )
    entry["parts"] = (
        DamagePart("physical", value, basic_damage=True, time_offset=0.2),
    )
    entry["applies_item_on_hits"] = {
        "effectiveness": 1.0,
        "hits": 1,
        "triggers": ("on_hit",),
    }
    entry["detail"] = (
        "One dash attack; reset, heal and Unsteady mark consumption are state branches."
    )
    return entry


def _defiant_dance(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    charge = min(max(float(ctx.options.get("w_charge", 1.0)), 0.0), 1.0)
    low = extract_named(ability, "Minimum Physical Damage", rank, ctx.stats, ctx.target)
    high = extract_named(
        ability, "Maximum Physical Damage", rank, ctx.stats, ctx.target
    )
    value = low + (high - low) * charge
    entry = damage_entry(
        ability.get("name", "Defiant Dance"),
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


def _flawless_duet(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Flawless Duet"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=0.4),)
    return entry


def _vanguard(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    passes = min(max(int(ctx.options.get("r_passes", 2)), 1), 2)
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Vanguard's Edge"),
        rank,
        extract_cooldown(ability, rank),
        value * passes,
        "magic",
    )
    entry["parts"] = (
        DamagePart("magic", value, count=passes, time_offset=0.25, hit_interval=2.5),
    )
    entry["event_order_certified"] = "initial barrage and one perimeter pass"
    return entry


SLOTS = {
    "P": _fervor,
    "Q": _bladesurge,
    "W": _defiant_dance,
    "E": _flawless_duet,
    "R": _vanguard,
}
parse_abilities = build_parser(SLOTS, "Irelia")
OPTIONS = [
    {
        "key": "p_stacks",
        "type": "int",
        "default": 4,
        "min": 0,
        "max": 4,
        "label": "Ionian Fervor stacks",
    },
    {
        "key": "w_charge",
        "type": "float",
        "default": 1.0,
        "min": 0.0,
        "max": 1.0,
        "step": 0.25,
        "label": "Defiant Dance charge fraction",
    },
    {
        "key": "r_passes",
        "type": "int",
        "default": 2,
        "min": 1,
        "max": 2,
        "label": "Vanguard's Edge passes",
    },
]
ASSUMPTIONS = [
    "Ionian Fervor's per-stack attack speed is applied before damage and its max-stack on-hit is explicit.",
    "Bladesurge is one full-effectiveness basic attack; Defiant Dance exposes the sourced charge interval.",
    "Vanguard's Edge models the initial barrage and one perimeter pass; marks, stun and slow are utility.",
]
SOURCES = [
    source_row(
        "Irelia parent entry",
        "https://wiki.leagueoflegends.com/en-us/Irelia",
        3892607,
        "2025-05-02T11:24:10Z",
    ),
    source_row(
        "Irelia Q template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Irelia/Q",
        2863950,
        "2019-11-03T19:57:08Z",
    ),
    source_row(
        "Irelia W template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Irelia/W",
        2864245,
        "2019-11-03T20:09:54Z",
    ),
    source_row(
        "Irelia E template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Irelia/E",
        2864391,
        "2019-11-03T20:12:25Z",
    ),
    source_row(
        "Irelia R template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Irelia/R",
        2864537,
        "2019-11-03T20:15:49Z",
    ),
]
MODULE_COVERAGE = {slot: "modeled" for slot in ("P", "Q", "W", "E", "R")}
REVIEW_STATUS = "reviewed_module"

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Irelia")
