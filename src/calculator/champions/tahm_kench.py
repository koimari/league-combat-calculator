"""Tahm Kench's acquired-taste and defensive-state packets."""

from typing import Any

from ..ability_spec import DamagePart
from .engine import ONHIT, SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    on_hit_entry,
    simple_damage,
)


def _acquired_taste(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("P")
    if ability is None:
        return None
    bonus = extract_named(
        ability, "Per-Level Scaling", ctx.level, ctx.stats, ctx.target
    )
    entry = on_hit_entry("An Acquired Taste", bonus, "magic")
    entry["detail"] = "basic attacks and Tongue Lash apply one stack"
    return entry


_acquired_taste.phase = ONHIT


def _tongue_lash(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("Q")
    if ability is None:
        return None
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None
    total = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    stacks = min(max(int(ctx.options.get("q_passive_stacks", 0)), 0), 3)
    if stacks:
        total += extract_named(
            ctx.ability("P") or ability,
            "Per-Level Scaling",
            ctx.level,
            ctx.stats,
            ctx.target,
        )
    entry = damage_entry(
        ability.get("name", "Tongue Lash"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", total, time_offset=0.0),)
    entry["detail"] = f"{stacks} Acquired Taste stack(s) before Q"
    return entry


def _regurgitate(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("R", 1)
    if ability is None:
        return None
    rank = ctx.rank_for("R")
    if rank < 1:
        return None
    total = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Regurgitate"),
        rank,
        extract_cooldown(ctx.ability("R") or ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", total, time_offset=0.4),)
    entry["detail"] = "enemy Regurgitate target"
    return entry


SLOTS = {
    "P": _acquired_taste,
    "Q": _tongue_lash,
    "W": simple_damage(attr="Magic Damage", dmg_type="magic"),
    # Thick Skin is grey-health/shield state, not damage; omitting it keeps
    # the damage timeline from inventing an enemy hit.
    "R": _regurgitate,
}

parse_abilities = build_parser(SLOTS, "Tahm Kench")

OPTIONS = [
    {
        "key": "q_passive_stacks",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 3,
        "label": "Acquired Taste stacks before Q",
    }
]

ASSUMPTIONS = [
    "An Acquired Taste is an explicit on-hit rider; Q may opt into the bonus damage from a pre-existing stack state.",
    "Thick Skin is modeled as defensive grey-health/shield state rather than direct damage.",
    "R defaults to the enemy Regurgitate branch; ally Devour is a separate support/shield scenario.",
]

SOURCES = [
    {
        "label": "Tahm Kench — full champion entry",
        "url": "https://wiki.leagueoflegends.com/en-us/Tahm_Kench",
        "revision_id": 4047230,
        "revision_timestamp": "2026-07-29T12:04:53Z",
    }
]
