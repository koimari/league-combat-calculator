"""Kalista's stateful combat packets.

The generated packet used Soul-Marked damage without an Oathsworn state and
treated Rend as a one-stack constant.  This module keeps those states
explicit, while every numeric value still comes from the pinned champion
cache and its full-entry Wiki receipt.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, extract_named


def _pierce(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("Q")
    if ability is None:
        return None
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None
    total = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Pierce"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", total, time_offset=0.0),)
    return entry


def _soul_marked(ctx: SlotCtx) -> dict[str, Any] | None:
    """W's damage only exists after both tethered marks are present."""
    if not bool(ctx.options.get("soul_mark_proc", False)):
        return None
    ability = ctx.ability("W")
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    if rank < 1:
        return None
    total = extract_named(ability, "Bonus Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        "Soul-Marked", rank, extract_cooldown(ability, rank), total, "magic"
    )
    entry["parts"] = (DamagePart("magic", total, time_offset=0.0),)
    entry["detail"] = "Oathsworn and Kalista marks consumed"
    return entry


def _rend(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("E")
    if ability is None:
        return None
    rank = ctx.rank_for("E")
    if rank < 1:
        return None
    stacks = min(max(int(ctx.options.get("rend_stacks", 1)), 1), 254)
    first = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    additional = extract_named(
        ability, "Bonus Damage per Additional Stack", rank, ctx.stats, ctx.target
    )
    total = first + max(0, stacks - 1) * additional
    entry = damage_entry(
        ability.get("name", "Rend"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", total, time_offset=0.0),)
    entry["detail"] = f"{stacks} Rend stack(s)"
    return entry


SLOTS = {
    "Q": _pierce,
    "W": _soul_marked,
    "E": _rend,
}

parse_abilities = build_parser(SLOTS, "Kalista")

OPTIONS = [
    {
        "key": "rend_stacks",
        "type": "int",
        "default": 1,
        "min": 1,
        "max": 254,
        "label": "Rend stacks",
    },
    {
        "key": "soul_mark_proc",
        "type": "bool",
        "default": False,
        "label": "Soul-Marked proc is armed",
    },
]

ASSUMPTIONS = [
    "W damage is withheld unless the Oathsworn and Kalista marks are explicitly armed.",
    "Rend defaults to one lodged spear; the stack count is explicit and capped at the sourced 254-stack limit.",
    "Fate's Call and Martial Poise are utility/state effects with no direct enemy damage.",
]

SOURCES = [
    {
        "label": "Kalista — full champion entry",
        "url": "https://wiki.leagueoflegends.com/en-us/Kalista",
        "revision_id": 4002537,
        "revision_timestamp": "2026-03-26T01:14:44Z",
    }
]
