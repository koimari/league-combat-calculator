"""Fiddlesticks' current-health Q, channelled W and timed R."""

from __future__ import annotations

from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from .engine import CC_PER_PART, SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .inputs import bool_option, int_option
from .module_helpers import no_damage
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    with_control,
)
from .source_receipts import load_champion_sources


def _scarecrow(ctx: SlotCtx) -> dict[str, Any] | None:
    return no_damage(
        ctx,
        name="A Harmless Scarecrow",
        reason="Effigy/sweeper state only; the full passive has no outgoing damage formula.",
        slot="P",
    )


def _terrify(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    feared = bool(ctx.option("q_target_already_feared"))
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
        ability_name(ability),
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


# The sourced fear interval rides the branch that actually fears: the
# doubled branch is reached only against a target that "cannot be affected
# by it again", so wrapping it would source a duration for a fear the cast
# does not apply.
_terrify_fearing = with_control(_terrify, kind="fear", duration_attr="Fear Duration")


def _terrify_slot(ctx: SlotCtx) -> dict[str, Any] | None:
    if bool(ctx.option("q_target_already_feared")):
        return _terrify(ctx)
    return _terrify_fearing(ctx)


def _bountiful_harvest(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    ticks = min(max(int(ctx.option("w_ticks")), 1), 8)
    per_instance = extract_named(
        ability, "Damage per Instance", rank, ctx.stats, ctx.target
    )
    final = extract_named(ability, "Last Tick of Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
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
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=0.4),)
    return entry


def _crowstorm(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    ticks = min(max(int(ctx.option("r_ticks")), 1), 20)
    per_tick = extract_named(
        ability, "Magic Damage per Tick", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability_name(ability),
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
    "Q": _terrify_slot,
    "W": _bountiful_harvest,
    "E": _reap,
    "R": _crowstorm,
}
# W tethers and reveals, R's crows only tick damage; E "slow[s] them for
# 1.25 seconds" (its centre silence is not an immobilize and is not in the
# vocabulary).  Q is absent because its fear is branch-conditional and is
# authored on the part in _terrify; P carries no damage part at all.
MODULE_CC = {"Q": CC_PER_PART, "W": "none", "E": "slow", "R": "none"}

parse_abilities = build_parser(SLOTS, "Fiddlesticks", cc_kinds=MODULE_CC)

OPTIONS = [
    bool_option(
        "q_target_already_feared",
        False,
        label="Terrify target already feared",
        rotation={
            "role": "irrelevant",
            "slot": "Q",
            "note": (
                "External pre-condition (fear from another source); "
                "modifies Q's damage branch, imposes no ordering "
                "constraint."
            ),
        },
    ),
    int_option("w_ticks", 8, minimum=1, maximum=8, label="Bountiful Harvest ticks"),
    int_option("r_ticks", 20, minimum=1, maximum=20, label="Crowstorm ticks"),
]

ASSUMPTIONS = [
    "Q's doubled branch is selected only for an already-feared target; current-health "
    "and minimum-damage thresholds remain sourced.",
    "W and R expose explicit tick counts and intervals; W's final missing-health tick "
    "is not averaged into the channel.",
    "Fear, silence, reveal, healing and Effigy behavior are recorded as "
    "state/utility, not invented TDD.",
]

SOURCES = load_champion_sources("Fiddlesticks")


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Fiddlesticks self-healing events from its authored packet."""
    healing = []
    w_ability = _healing.ability_json(champion_data, "W")
    w_rank = _healing.parsed_rank(ability_damages, "W")
    portion = (
        extract_named(w_ability, "Champion Heal Portion", w_rank, champion_stats, {})
        / 100.0
    )
    for event in _healing.attributed_events(
        damage_events, lambda source, _event: source == "W"
    ):
        dealt = float(event.get("raw_damage", event.get("damage", 0.0)) or 0.0)
        _healing.heal_from_damage(healing, event, portion * dealt, "Bountiful Harvest")
    return healing


SELF_HEALING_RULE = self_healing_rule("Fiddlesticks")(derive_self_healing)
