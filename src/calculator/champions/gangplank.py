"""Gangplank's burning passive, attack-like Parrrley and cannon waves."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import no_damage, source_row
from .slotlib import damage_entry, extract_cooldown, extract_named


def _trial_by_fire(ctx: SlotCtx, ability: dict[str, Any]) -> float:
    return extract_named(ability, "Bonus True Damage", ctx.level, ctx.stats, ctx.target)


def _trial_proc(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    procs = min(max(int(ctx.option("p_procs")), 0), 10)
    if procs <= 0:
        return no_damage(
            ctx,
            name="Trial by Fire",
            reason="Passive burn is ready only when an empowered attack is selected.",
            slot="P",
        )
    per_tick = _trial_by_fire(ctx, ability) / 10.0
    entry = {
        "name": "Trial by Fire",
        "damage_type": "true",
        "total_raw": per_tick * 10 * procs,
        "parts": (
            DamagePart("true", per_tick, count=10, time_offset=0.0, hit_interval=0.25),
        ),
        "proc_count": procs,
        "detail": f"{procs} empowered attacks, each burning for 2.5 seconds.",
    }
    return entry


def _parrrley(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Parrrley"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "physical",
    )
    entry["parts"] = (
        DamagePart("physical", value, crit_effectiveness=1.0, basic_damage=True),
    )
    entry["applies_item_on_hits"] = {
        "effectiveness": 1.0,
        "hits": 1,
        "triggers": ("on_hit", "on_attack"),
    }
    entry["detail"] = (
        "Ranged attack: applies on-hit/on-attack effects and may critically strike for the sourced 230% modifier."
    )
    return entry


def _remove_scurvy(ctx: SlotCtx) -> dict[str, Any] | None:
    return no_damage(
        ctx,
        name="Remove Scurvy",
        reason="Heal and cleanse only; no outgoing damage is listed.",
    )


def _powder_keg(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    bonus = extract_named(ability, "Bonus Champion Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Powder Keg"),
        rank,
        extract_cooldown(ability, rank),
        bonus,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", bonus),)
    entry["detail"] = (
        "Champion keg branch: triggering attack plus the sourced bonus; 40% armor-ignore is retained in provenance."
    )
    return entry


def _cannon_barrage(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    fire_at_will = bool(ctx.options.get("r_fire_at_will", False))
    deaths_daughter = bool(ctx.options.get("r_deaths_daughter", False))
    waves = 18 if fire_at_will else 12
    magic_attr = "Magic Damage Per Wave"
    per_wave = extract_named(ability, magic_attr, rank, ctx.stats, ctx.target)
    total = per_wave * waves
    parts: list[DamagePart] = [
        DamagePart("magic", per_wave, count=waves, time_offset=0.0, hit_interval=0.6667)
    ]
    if deaths_daughter:
        true = extract_named(
            ability, "True Damage with Death's Daughter", rank, ctx.stats, ctx.target
        )
        total += true
        parts.append(DamagePart("true", true, time_offset=2.25))
    entry = damage_entry(
        ability.get("name", "Cannon Barrage"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = tuple(parts)
    entry["detail"] = (
        f"{waves} wave(s); Fire at Will={'on' if fire_at_will else 'off'}, Death's Daughter={'on' if deaths_daughter else 'off'}."
    )
    return entry


SLOTS = {
    "P": _trial_proc,
    "Q": _parrrley,
    "W": _remove_scurvy,
    "E": _powder_keg,
    "R": _cannon_barrage,
}
parse_abilities = build_parser(SLOTS, "Gangplank")

OPTIONS = [
    {
        "key": "p_procs",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 10,
        "label": "Trial by Fire procs",
    },
    {
        "key": "r_fire_at_will",
        "type": "bool",
        "default": False,
        "label": "Cannon Barrage Fire at Will upgrade",
    },
    {
        "key": "r_deaths_daughter",
        "type": "bool",
        "default": False,
        "label": "Cannon Barrage Death's Daughter upgrade",
    },
]

ASSUMPTIONS = [
    "Trial by Fire is an explicit 10-tick true-damage burn per empowered attack; Parrrley cannot also apply it.",
    "Powder Keg's triggering attack is a separate authored input; the packet retains the bonus champion branch and armor-ignore note instead of fabricating the trigger.",
    "Cannon Barrage exposes the 12/18-wave and Death's Daughter branches with ordered tick events.",
]

SOURCES = [
    source_row(
        "Gangplank parent entry",
        "https://wiki.leagueoflegends.com/en-us/Gangplank",
        4002542,
        "2026-03-26T01:37:40Z",
    ),
    source_row(
        "Gangplank Q template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Gangplank/Q",
        2863942,
        "2019-11-03T19:57:00Z",
    ),
    source_row(
        "Gangplank W template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Gangplank/W",
        2864237,
        "2019-11-03T20:09:46Z",
    ),
    source_row(
        "Gangplank E template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Gangplank/E",
        2864383,
        "2019-11-03T20:12:16Z",
    ),
    source_row(
        "Gangplank R template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Gangplank/R",
        2864529,
        "2019-11-03T20:15:41Z",
    ),
]
MODULE_COVERAGE = {slot: "modeled" for slot in ("P", "Q", "W", "E", "R")}
REVIEW_STATUS = "reviewed_module"

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Gangplank")
