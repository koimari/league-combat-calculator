"""Ornn's authored multi-hit combat timeline.

Coverage: P (Living Forge) is out of scope, and for two reasons at once.
Master Craftsman's Masterwork upgrades are shop economics, an axis the
engine does not have. Temper's Brittle consume — 9% : 17.94% of the
target's maximum health when an immobilise breaks the debuff — is a real
damage rider, but the cached passive carries no leveling row for it
(every effect in ``data/champions.json`` Ornn P has ``leveling: []``);
the percentage lives only in the Temper description prose. Pricing it
means a prose-sourced per-level array plus a Brittle apply-and-consume
timeline, which is a champion-module unit, not a relabel.  The pinned
packet's ``kind: "no_damage"`` for P records that no *leveling row* is
listed; it is not evidence the ability deals none, so the slot stays
out_of_scope rather than being relabelled.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import CC_PER_PART, SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, extract_named, simple_damage
from .source_receipts import load_champion_sources
from .inputs import int_option


def _bellows_breath(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked("W")
    if ranked is None:
        return None
    ability, rank = ranked
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


# "Call of the Forge God can be recast after 1.25 seconds while the
# elemental is active" — the cadence between the two priced passes.
_R_RECAST_DELAY = 1.25
# The control each pass applies: the outbound stampede slows, the recast
# pass "knocks them up and stuns them", two immobilize kinds at once.
_R_PASS_CC_KINDS = ("slow", "immobilize")


def _call_of_the_forge_god(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked("R")
    if ranked is None:
        return None
    ability, rank = ranked
    passes = min(max(int(ctx.option("r_passes")), 1), 2)
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
    # One part per pass, because the two passes apply different control:
    # the stampede out "slows them for 2 seconds", and the recast pass
    # "knocks them up and stuns them for 1 second".  A single count=2 part
    # would have to answer both with one kind, so the passes are authored
    # separately at the same 1.25-second cadence they already had.
    entry["parts"] = tuple(
        DamagePart(
            "magic",
            per_pass,
            time_offset=index * _R_RECAST_DELAY,
            cc_kind=_R_PASS_CC_KINDS[index],
        )
        for index in range(passes)
    )
    entry["detail"] = f"{passes} elemental pass(es); each pass applies Brittle"
    return entry


SLOTS = {
    # The fissure and the charge each damage what they cross once, with no
    # sourced sub-cast phase, so each certifies the cast boundary its
    # reviewed control rides on.
    "Q": simple_damage(
        attr="Physical Damage",
        dmg_type="physical",
        event_order_certified="single_hit",
    ),
    "W": _bellows_breath,
    "E": simple_damage(
        attr="Physical Damage",
        dmg_type="physical",
        event_order_certified="single_hit",
    ),
    "R": _call_of_the_forge_god,
}

# Cached kit review.  Q's fissure "deals physical damage to enemies hit and
# slows them by 40% for 2 seconds"; its magma pillar knocks aside a second
# later but deals nothing.  W's ticks only damage — the Brittle they apply
# is a debuff other control consumes, not a control class of its own.  E's
# priced row is the charge's pass-through damage, which applies nothing:
# the knock-up and stun belong to the terrain-collision shockwave, whose
# own damage lands only on enemies "not already hit by the charge" and
# whose collision this module does not model.  R answers per part instead
# of here, because its two passes apply different control
# (``_call_of_the_forge_god``).
MODULE_CC = {"Q": "slow", "W": "none", "E": "none", "R": CC_PER_PART}

parse_abilities = build_parser(SLOTS, "Ornn", cc_kinds=MODULE_CC)

OPTIONS = [int_option("r_passes", 2, minimum=1, maximum=2, label="R elemental passes")]

ASSUMPTIONS = [
    "Bellows Breath uses five sourced 0.15-second ticks and exposes the final-gout Brittle state in its detail receipt.",
    "Call of the Forge God defaults to both sourced passes; one pass is available as an explicit option.",
    "Living Forge and Master Craftsman are item/state systems, not direct enemy damage.",
    "P (Living Forge) lists no enemy-damage leveling row (the pinned "
    "reviewed packet declares P kind='no_damage' on that basis, and it "
    "is not a cast slot in this module's SLOTS map), but Temper's "
    "Brittle consume is a real prose-sourced max-health rider, so the "
    "slot stays out_of_scope — an unpriced formula, not a zero row.",
]

SOURCES = load_champion_sources("Ornn")
