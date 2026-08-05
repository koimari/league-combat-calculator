"""Garen's empowered Q, spin cadence and missing-health ultimate."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .reviewed_batch_01 import no_damage, source_row
from .slotlib import damage_entry, extract_cooldown, extract_named


def _perseverance(ctx: SlotCtx) -> dict[str, Any] | None:
    return no_damage(
        ctx,
        name="Perseverance",
        reason="Out-of-combat regeneration is self sustain, not outgoing damage.",
        slot="P",
    )


def _decisive_strike(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "Bonus Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Decisive Strike"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", value, basic_damage=True),)
    entry["empowers_next_auto"] = True
    entry["detail"] = (
        "One uncancellable, silencing empowered basic attack; slow cleanse/movement speed are state-only."
    )
    return entry


def _courage(ctx: SlotCtx) -> dict[str, Any] | None:
    return no_damage(
        ctx,
        name="Courage",
        reason="Courage resist stacks, shield and damage reduction are defensive state.",
    )


_courage.phase = BUFF


def _judgment(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    nearest = bool(ctx.options.get("e_nearest_target", True))
    spins = 7 + int(max(0.0, ctx.stats.get("bonus_attack_speed", 0.0)) // 25.0)
    spins = min(max(spins, 7), 15)
    attr = "Increased Damage Per Spin" if nearest else "Physical Damage Per Spin"
    per_spin = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Judgment"),
        rank,
        extract_cooldown(ability, rank),
        per_spin * spins,
        "physical",
    )
    entry["parts"] = (
        DamagePart(
            "physical", per_spin, count=spins, time_offset=0.0, hit_interval=3.0 / spins
        ),
    )
    entry["detail"] = (
        f"{spins} spin(s); nearest-target 25% branch={'on' if nearest else 'off'}. Six hits apply the sourced 25% armor reduction."
    )
    entry["target_debuff"] = {
        "armor_reduction_percent": 25.0,
        "duration": 6.0,
        "threshold_hits": 6,
    }
    return entry


def _demacian_justice(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "True Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Demacian Justice"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "true",
    )
    entry["parts"] = (DamagePart("true", value, time_offset=0.435),)
    entry["event_order_certified"] = "single_hit"
    entry["target_max_health_sensitive"] = True
    entry["detail"] = (
        "True damage scales from target missing health; the execute/reveal threshold is target state."
    )
    return entry


SLOTS = {
    "P": _perseverance,
    "Q": _decisive_strike,
    "W": _courage,
    "E": _judgment,
    "R": _demacian_justice,
}
parse_abilities = build_parser(SLOTS, "Garen")

OPTIONS = [
    {
        "key": "e_nearest_target",
        "type": "bool",
        "default": True,
        "label": "Judgment nearest-target branch",
    },
]

ASSUMPTIONS = [
    "Judgment uses the sourced 7 + 1 per 25% bonus attack speed spin count and exposes the nearest-target 25% branch.",
    "The armor reduction is retained as an ordered effect after the six-hit threshold; it is never allowed to boost the first six spins.",
    "Perseverance and Courage are defensive/self-state rows and do not enter TDD.",
]

SOURCES = [
    source_row(
        "Garen parent entry",
        "https://wiki.leagueoflegends.com/en-us/Garen",
        3892614,
        "2025-05-02T11:24:26Z",
    ),
    source_row(
        "Garen Q template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Garen/Q",
        2863943,
        "2019-11-03T19:57:00Z",
    ),
    source_row(
        "Garen W template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Garen/W",
        2864238,
        "2019-11-03T20:09:47Z",
    ),
    source_row(
        "Garen E template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Garen/E",
        2864384,
        "2019-11-03T20:12:17Z",
    ),
    source_row(
        "Garen R template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Garen/R",
        2864530,
        "2019-11-03T20:15:42Z",
    ),
]
MODULE_COVERAGE = {slot: "modeled" for slot in ("P", "Q", "W", "E", "R")}
REVIEW_STATUS = "reviewed_module"
