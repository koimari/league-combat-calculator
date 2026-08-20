"""Fiddlesticks' current-health Q, channelled W and timed R."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .healing_contract import declare_healing_rule
from .module_helpers import no_damage
from .slotlib import damage_entry, extract_cooldown, extract_named
from .source_receipts import load_champion_sources


def _scarecrow(ctx: SlotCtx) -> dict[str, Any] | None:
    return no_damage(
        ctx,
        name="A Harmless Scarecrow",
        reason="Effigy/sweeper state only; the full passive has no outgoing damage formula.",
        slot="P",
    )


def _terrify(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    feared = bool(ctx.options.get("q_target_already_feared", False))
    attr = "Increased Magic Damage" if feared else "Magic Damage"
    value = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    minimum = extract_named(
        ability,
        "Increased Minimum Damage" if feared else "Minimum Damage",
        rank,
        ctx.stats,
        ctx.target,
    )
    value = max(value, minimum)
    entry = damage_entry(
        ability.get("name", "Terrify"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    # Terrify's control is a property of the branch, not of the slot, so it
    # is authored here rather than in MODULE_CC: the doubled branch is
    # reached only against a target that "cannot be affected by it again",
    # i.e. one this cast does not fear.
    entry["parts"] = (
        DamagePart(
            "magic", value, time_offset=0.35, cc_kind="none" if feared else "fear"
        ),
    )
    entry["target_max_health_sensitive"] = True
    entry["detail"] = (
        "Already-feared target uses the sourced doubled current-health branch."
    )
    return entry


def _bountiful_harvest(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    ticks = min(max(int(ctx.option("w_ticks")), 1), 8)
    per_instance = extract_named(
        ability, "Damage per Instance", rank, ctx.stats, ctx.target
    )
    final = extract_named(ability, "Last Tick of Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Bountiful Harvest"),
        rank,
        extract_cooldown(ability, rank),
        per_instance * ticks + final,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic", per_instance, count=ticks, time_offset=0.0, hit_interval=0.25
        ),
        DamagePart("magic", final, time_offset=2.0),
    )
    entry["target_max_health_sensitive"] = True
    entry["detail"] = (
        f"{ticks} channel tick(s) plus the sourced missing-health final tick; heal is non-TDD."
    )
    return entry


def _reap(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Reap"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=0.4),)
    return entry


def _crowstorm(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    ticks = min(max(int(ctx.option("r_ticks")), 1), 20)
    per_tick = extract_named(
        ability, "Magic Damage per Tick", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability.get("name", "Crowstorm"),
        rank,
        extract_cooldown(ability, rank),
        per_tick * ticks,
        "magic",
    )
    entry["parts"] = (
        DamagePart("magic", per_tick, count=ticks, time_offset=1.5, hit_interval=0.25),
    )
    entry["detail"] = f"{ticks} sourced crows tick(s) over the 5-second zone."
    return entry


SLOTS = {
    "P": _scarecrow,
    "Q": _terrify,
    "W": _bountiful_harvest,
    "E": _reap,
    "R": _crowstorm,
}
# W tethers and reveals, R's crows only tick damage; E "slow[s] them for
# 1.25 seconds" (its centre silence is not an immobilize and is not in the
# vocabulary).  Q is absent because its fear is branch-conditional and is
# authored on the part in _terrify; P carries no damage part at all.
MODULE_CC = {"W": "none", "E": "slow", "R": "none"}

parse_abilities = build_parser(SLOTS, "Fiddlesticks", cc_kinds=MODULE_CC)

OPTIONS = [
    {
        "key": "q_target_already_feared",
        "type": "bool",
        "default": False,
        "label": "Terrify target already feared",
        "rotation": {
            "role": "irrelevant",
            "slot": "Q",
            "note": (
                "External pre-condition (fear from another source); "
                "modifies Q's damage branch, imposes no ordering "
                "constraint."
            ),
        },
    },
    {
        "key": "w_ticks",
        "type": "int",
        "default": 8,
        "min": 1,
        "max": 8,
        "label": "Bountiful Harvest ticks",
    },
    {
        "key": "r_ticks",
        "type": "int",
        "default": 20,
        "min": 1,
        "max": 20,
        "label": "Crowstorm ticks",
    },
]

ASSUMPTIONS = [
    "Q's doubled branch is selected only for an already-feared target; current-health and minimum-damage thresholds remain sourced.",
    "W and R expose explicit tick counts and intervals; W's final missing-health tick is not averaged into the channel.",
    "Fear, silence, reveal, healing and Effigy behavior are recorded as state/utility, not invented TDD.",
]

SOURCES = load_champion_sources("Fiddlesticks")

SELF_HEALING_RULE = declare_healing_rule("Fiddlesticks")
