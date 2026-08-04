"""Qiyana's element and on-hit state packets."""

from typing import Any

from ..ability_spec import DamagePart
from .engine import ONHIT, SlotCtx, build_parser
from .slotlib import (
    ability_on_hit_entry,
    damage_entry,
    extract_cooldown,
    extract_named,
    on_hit_entry,
    simple_damage,
)


def _royal_privilege(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("P")
    if ability is None:
        return None
    total = extract_named(
        ability, "Bonus Physical Damage", ctx.level, ctx.stats, ctx.target
    )
    return on_hit_entry("Royal Privilege", total, "physical")


_royal_privilege.phase = ONHIT


def _edge_of_ixtal(ctx: SlotCtx) -> dict[str, Any] | None:
    ability_index = 1 if int(ctx.options.get("q_variant", 0)) > 0 else 0
    ability = ctx.ability("Q", ability_index)
    if ability is None:
        return None
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None
    variant = min(max(int(ctx.options.get("q_variant", 0)), 0), 2)
    low_health = bool(ctx.options.get("q_target_below_half", False))
    attr = "Increased Damage" if variant == 2 and low_health else "Physical Damage"
    total = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Edge of Ixtal"),
        rank,
        extract_cooldown(ctx.ability("Q", 0) or ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", total, time_offset=0.0),)
    entry["detail"] = (
        "Terrain element, target below 50% HP"
        if variant == 2 and low_health
        else "Elemental Q"
    )
    return entry


def _terrashape(ctx: SlotCtx) -> dict[str, Any] | None:
    """Terrashape's bonus is an on-hit rider, not a direct spell hit."""
    ability = ctx.ability("W")
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    if rank < 1:
        return None
    total = extract_named(ability, "Bonus Magic Damage", rank, ctx.stats, ctx.target)
    entry = ability_on_hit_entry(
        "Terrashape element",
        rank,
        "magic",
        {
            "name": "Terrashape element (on-hit)",
            "damage_per_hit": total,
            "damage_type": "magic",
        },
    )
    return entry


_terrashape.phase = ONHIT


def _supreme_display(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("R")
    if ability is None:
        return None
    rank = ctx.rank_for("R")
    if rank < 1:
        return None
    total = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Supreme Display of Talent"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", total, time_offset=0.0),)
    return entry


SLOTS = {
    "P": _royal_privilege,
    "Q": _edge_of_ixtal,
    "W": _terrashape,
    "E": simple_damage(attr="Physical Damage", dmg_type="physical"),
    "R": _supreme_display,
}

parse_abilities = build_parser(SLOTS, "Qiyana")

OPTIONS = [
    {
        "key": "q_variant",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 2,
        "label": "Q element (edge, brush/river, terrain)",
    },
    {
        "key": "q_target_below_half",
        "type": "bool",
        "default": False,
        "label": "Terrain Q target below 50% health",
    },
]

ASSUMPTIONS = [
    "Royal Privilege and Terrashape are modeled as on-hit riders; they are not free direct spell damage.",
    "Terrain Q's increased damage is enabled only when the target-below-half state is explicit.",
    "Element control and per-target passive cooldowns remain explicit scenario state.",
]

SOURCES = [
    {
        "label": "Qiyana — full champion entry",
        "url": "https://wiki.leagueoflegends.com/en-us/Qiyana",
        "revision_id": 4007961,
        "revision_timestamp": "2026-04-12T23:59:09Z",
    }
]
