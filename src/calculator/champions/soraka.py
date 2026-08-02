"""Soraka — revision-backed offensive slot map.

Starcall deals one magic hit. Equinox deals one hit on cast and the same hit
again after 1.5 seconds when the target remains in the zone. Its second hit is
an explicit option because crowd control does not guarantee that condition.
Soraka's passive, W, and R do not damage enemies.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import extract_cooldown, extract_named, simple_damage


def _equinox(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: initial hit plus the optional equal-damage eruption."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    per_hit = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    second_hit = bool(ctx.options.get("e_second_hit", True))
    count = 2 if second_hit else 1
    entry: dict[str, Any] = {
        "name": ability.get("name", "Equinox"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "parts": (DamagePart("magic", per_hit, count=count),),
        "total_raw": per_hit * count,
        "damage_type": "magic",
        "detail": "Initial hit + eruption" if second_hit else "Initial hit only",
    }
    if second_hit:
        # The eruption refreshes ability-triggered item burns 1.5s later.
        entry["dot_duration"] = 1.5
    return entry


OPTIONS = [
    {
        "key": "e_second_hit",
        "type": "bool",
        "default": True,
        "label": "Target remains for E eruption",
    },
]

ASSUMPTIONS = [
    "Starcall counts one enemy-champion hit.",
    "Equinox's eruption is counted only when its target-remains option is on.",
    "Passive, Astral Infusion, and Wish are excluded because they deal no enemy damage.",
]

SOURCES = [
    {
        "label": "Starcall",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Soraka/Starcall",
        "revision_id": 3953362,
        "revision_timestamp": "2025-09-11T19:22:43Z",
    },
    {
        "label": "Equinox",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Soraka/Equinox",
        "revision_id": 3907153,
        "revision_timestamp": "2025-06-06T18:23:34Z",
    },
]

SLOTS = {
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "E": _equinox,
}

parse_abilities = build_parser(SLOTS, "Soraka")
