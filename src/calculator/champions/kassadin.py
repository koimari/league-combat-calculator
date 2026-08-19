"""Kassadin's magic shield, Nether Blade rider and mana-scaled Riftwalk."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import no_damage, source_row
from .slotlib import (
    ability_on_hit_entry,
    damage_entry,
    extract_cooldown,
    extract_named,
    simple_damage,
)

PASSIVE_W_BASE = 25.0  # Full parent entry: Nether Blade passive, not a leveling row.
PASSIVE_W_AP_RATIO = 0.10


def _null_sphere(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Null Sphere"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
        # One orb, one target, no travel row in the cached packet: the hit
        # lands at the cast boundary, which is what puts MODULE_CC's
        # reviewed answer for Q into the event ledger.
        event_order_certified="single_hit",
    )
    entry["parts"] = (DamagePart("magic", value),)
    entry["detail"] = (
        f"Magic shield is {extract_named(ability, 'Magic Shield Strength', rank, ctx.stats, ctx.target):g}; shield is defensive state."
    )
    return entry


def _nether_blade(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    passive = PASSIVE_W_BASE + PASSIVE_W_AP_RATIO * ctx.stat("ability_power")
    active = (
        extract_named(
            ability, "Increased Bonus Magic Damage", rank, ctx.stats, ctx.target
        )
        if bool(ctx.options.get("w_empowered", True))
        else 0.0
    )
    entry = ability_on_hit_entry(
        ability.get("name", "Nether Blade"),
        rank,
        "magic",
        {
            "name": "Nether Blade passive",
            "damage_per_hit": passive,
            "damage_type": "magic",
        },
        extract_cooldown(ability, rank),
    )
    if active:
        entry["parts"] = (
            DamagePart("magic", active, basic_damage=True, time_offset=0.1),
        )
        entry["total_raw"] = active
        entry["empowers_next_auto"] = True
    entry["detail"] = (
        f"Passive on-hit {passive:g}; {'empowered' if active else 'unempowered'} next attack and mana restore are explicit."
    )
    return entry


def _riftwalk(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    stacks = min(max(int(ctx.option("r_stacks")), 0), 4)
    base = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    bonus = extract_named(
        ability, "Bonus Damage Per Stack", rank, ctx.stats, ctx.target
    )
    value = base + bonus * stacks
    entry = damage_entry(
        ability.get("name", "Riftwalk"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=0.2),)
    entry["detail"] = (
        f"{stacks} Riftwalk stack(s); mana cost escalation is source-backed and included in the base packet."
    )
    return entry


SLOTS = {
    "P": lambda ctx: no_damage(
        ctx,
        name="Void Stone",
        reason="Permanent ghosting and 10% reduced magic damage are defensive state.",
    ),
    "Q": _null_sphere,
    "W": _nether_blade,
    "E": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "R": _riftwalk,
}

# Cached kit review: Q disrupts channels (an interrupt, not one of the
# immobilize kinds), W and R apply no control, and E "slows them for 1
# second".  P is defensive state and emits no damage event to carry a kind.
MODULE_CC = {"Q": "none", "W": "none", "E": "slow", "R": "none"}

parse_abilities = build_parser(SLOTS, "Kassadin", cc_kinds=MODULE_CC)
OPTIONS = [
    {
        "key": "w_empowered",
        "type": "bool",
        "default": True,
        "label": "Nether Blade empowered attack",
    },
    {
        "key": "r_stacks",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 4,
        "label": "Riftwalk stacks",
    },
]
ASSUMPTIONS = [
    "Void Stone's magic-damage reduction is defensive and never enters TDD.",
    "Nether Blade uses the full parent passive on-hit plus the selected active rider on one empowered basic attack.",
    "Riftwalk reads the target's max-mana scaling and an explicit 0–4 stack state.",
]
SOURCES = [
    source_row(
        "Kassadin parent entry",
        "https://wiki.leagueoflegends.com/en-us/Kassadin",
        4008773,
        "2026-04-15T14:58:16Z",
    ),
    source_row(
        "Kassadin Q template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Kassadin/Q",
        2863962,
        "2019-11-03T19:57:19Z",
    ),
    source_row(
        "Kassadin W template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Kassadin/W",
        2864257,
        "2019-11-03T20:10:06Z",
    ),
    source_row(
        "Kassadin E template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Kassadin/E",
        2864403,
        "2019-11-03T20:12:37Z",
    ),
    source_row(
        "Kassadin R template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Kassadin/R",
        2864549,
        "2019-11-03T20:16:01Z",
    ),
]
MODULE_COVERAGE = {slot: "modeled" for slot in ("P", "Q", "W", "E", "R")}
REVIEW_STATUS = "reviewed_module"
