"""Ornn's authored multi-hit combat timeline."""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, extract_named, simple_damage


def _bellows_breath(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("W")
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    if rank < 1:
        return None
    per_tick = extract_named(
        ability, "Magic Damage Per Tick", rank, ctx.stats, ctx.target
    )
    total = per_tick * 5
    entry = damage_entry(
        ability.get("name", "Bellows Breath"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart("magic", per_tick, count=5, time_offset=0.0, hit_interval=0.15),
    )
    entry["detail"] = "five sourced 0.15-second fire ticks; final gout applies Brittle"
    return entry


def _call_of_the_forge_god(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("R")
    if ability is None:
        return None
    rank = ctx.rank_for("R")
    if rank < 1:
        return None
    passes = min(max(int(ctx.options.get("r_passes", 2)), 1), 2)
    attr = "Total Magic Damage" if passes == 2 else "Magic Damage"
    total = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    per_pass = total / passes
    entry = damage_entry(
        ability.get("name", "Call of the Forge God"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            per_pass,
            count=passes,
            time_offset=0.0,
            hit_interval=1.25 if passes > 1 else None,
        ),
    )
    entry["detail"] = f"{passes} elemental pass(es); each pass applies Brittle"
    return entry


SLOTS = {
    "Q": simple_damage(attr="Physical Damage", dmg_type="physical"),
    "W": _bellows_breath,
    "E": simple_damage(attr="Physical Damage", dmg_type="physical"),
    "R": _call_of_the_forge_god,
}

parse_abilities = build_parser(SLOTS, "Ornn")

OPTIONS = [
    {
        "key": "r_passes",
        "type": "int",
        "default": 2,
        "min": 1,
        "max": 2,
        "label": "R elemental passes",
    }
]

ASSUMPTIONS = [
    "Bellows Breath uses five sourced 0.15-second ticks and exposes the final-gout Brittle state in its detail receipt.",
    "Call of the Forge God defaults to both sourced passes; one pass is available as an explicit option.",
    "Living Forge and Master Craftsman are item/state systems, not direct enemy damage.",
]

SOURCES = [
    {
        "label": "Ornn — full champion entry",
        "url": "https://wiki.leagueoflegends.com/en-us/Ornn",
        "revision_id": 4012186,
        "revision_timestamp": "2026-04-25T08:28:03Z",
    }
]
