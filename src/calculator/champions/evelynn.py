"""Evelynn's mark/recast Q, charm shred and execute-gated ultimate."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import no_damage, source_row
from .slotlib import damage_entry, extract_cooldown, extract_named, extract_value


def _demon_shade(ctx: SlotCtx) -> dict[str, Any] | None:
    return no_damage(
        ctx,
        name="Demon Shade",
        reason="Camouflage and low-health regeneration are self-state; no outgoing damage is implied.",
        slot="P",
    )


def _hate_spike(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    recasts = min(max(int(ctx.options.get("q_recasts", 3)), 0), 3)
    marked = bool(ctx.options.get("q_marked_target", True))
    dart = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    spike = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    marked_bonus = extract_named(
        ability, "Bonus Magic Damage", rank, ctx.stats, ctx.target
    )
    total = dart + recasts * (spike + (marked_bonus if marked else 0.0))
    entry = damage_entry(
        ability.get("name", "Hate Spike"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    parts = [DamagePart("magic", dart, time_offset=0.3)]
    for index in range(recasts):
        parts.append(
            DamagePart(
                "magic",
                spike + (marked_bonus if marked else 0.0),
                time_offset=0.6 + 0.3 * index,
            )
        )
    entry["parts"] = tuple(parts)
    entry["detail"] = (
        f"Dart plus {recasts} recast spike(s); mark bonus {'on' if marked else 'off'}."
    )
    return entry


def _allure(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    entry = no_damage(
        ctx,
        name=ability.get("name", "Allure"),
        reason="Charm/slow is selected from the full W entry; champion target is the default branch.",
    )
    if entry is None:
        return None
    if bool(ctx.options.get("w_charmed", True)):
        shred = extract_value(ability, "Magic Resistance Reduction", rank)
        entry["target_debuff"] = {"mr_reduction_percent": shred, "duration": 4.0}
        entry["detail"] = (
            f"Charmed champion branch: {shred:g}% magic-resistance reduction for 4 seconds."
        )
    return entry


def _whiplash(ctx: SlotCtx) -> dict[str, Any] | None:
    empowered = bool(ctx.options.get("e_empowered", False))
    index = 1 if empowered else 0
    ability = ctx.ability("E", index)
    base_ability = ctx.ability("E", 0)
    if ability is None or base_ability is None:
        return None
    rank = ctx.rank_for("E")
    if rank < 1:
        return None
    attr = "Empowered Magic Damage" if empowered else "Magic Damage"
    value = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Whiplash"),
        rank,
        extract_cooldown(base_ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value),)
    entry["target_max_health_sensitive"] = True
    # Wiki: Whiplash applies on-hit effects (empowered variant only to the
    # primary target — the module models the primary hit).
    entry["applies_item_on_hits"] = {
        "effectiveness": 1.0,
        "hits": 1,
        "triggers": ("on_hit",),
    }
    entry["detail"] = "Empowered Whiplash applies on-hit only to its primary target."
    return entry


def _last_caress(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    execute = bool(ctx.options.get("r_execute_ready", False))
    attr = "Empowered Damage" if execute else "Magic Damage"
    value = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Last Caress"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=0.35),)
    entry["detail"] = (
        "240% execute branch is opt-in only when the target is below 30% maximum health."
    )
    return entry


SLOTS = {
    "P": _demon_shade,
    "Q": _hate_spike,
    "W": _allure,
    "E": _whiplash,
    "R": _last_caress,
}
parse_abilities = build_parser(SLOTS, "Evelynn")

OPTIONS = [
    {
        "key": "q_recasts",
        "type": "int",
        "default": 3,
        "min": 0,
        "max": 3,
        "label": "Hate Spike recasts",
    },
    {
        "key": "q_marked_target",
        "type": "bool",
        "default": True,
        "label": "Hate Spike mark is active",
    },
    {
        "key": "w_charmed",
        "type": "bool",
        "default": True,
        "label": "Allure fully charmed champion",
    },
    {
        "key": "e_empowered",
        "type": "bool",
        "default": False,
        "label": "Empowered Whiplash",
    },
    {
        "key": "r_execute_ready",
        "type": "bool",
        "default": False,
        "label": "Last Caress execute branch",
    },
]

ASSUMPTIONS = [
    "Hate Spike requires an explicit recast count and mark state; neither is inferred from a single rotation.",
    "Allure's champion branch applies the sourced MR shred only when the full charm is selected; monster-only bonus damage is not silently mixed into champion TDD.",
    "Last Caress uses the 240% branch only below the sourced 30% target-health threshold.",
]

SOURCES = [
    source_row(
        "Evelynn parent entry",
        "https://wiki.leagueoflegends.com/en-us/Evelynn",
        4034409,
        "2026-06-22T16:08:34Z",
    ),
    source_row(
        "Evelynn Q template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Evelynn/Q",
        2863936,
        "2019-11-03T19:56:53Z",
    ),
    source_row(
        "Evelynn W template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Evelynn/W",
        2864231,
        "2019-11-03T20:09:40Z",
    ),
    source_row(
        "Evelynn E template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Evelynn/E",
        2864377,
        "2019-11-03T20:12:10Z",
    ),
    source_row(
        "Evelynn R template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Evelynn/R",
        2864523,
        "2019-11-03T20:15:35Z",
    ),
]
MODULE_COVERAGE = {slot: "modeled" for slot in ("P", "Q", "W", "E", "R")}
REVIEW_STATUS = "reviewed_module"
