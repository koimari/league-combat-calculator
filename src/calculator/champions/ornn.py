"""Ornn's authored multi-hit combat timeline.

P (Living Forge) is ``modeled`` through Temper's Brittle consume, which
rides R as a ``post_hit_proc`` (``_temper_consume``).  The other two
innates on the same slot are shop economics, an axis the engine does not
have: Living Forge's remote purchase and Master Craftsman's Masterwork
upgrades, whose 10% : 30% bonus-resist-and-health rider is a self-buff no
enemy takes.  Every effect in ``data/champions.json`` Ornn P carries
``leveling: []``, so the consume's percentage is read out of the Temper
description prose and cross-checked against the game file — see
``_temper_consume_percent``.
"""

import re
from typing import Any

from ..ability_spec import DamagePart
from ..stats import MAX_LEVEL
from .engine import CC_PER_PART, SlotCtx, build_parser
from .module_contract import coverage
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    post_hit_proc_row,
    simple_damage,
)
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
    # Both cached W rows carry the unit "% of target's maximum health", so
    # every tick is priced off the target's maximum health — the same stamp
    # R's Temper consume carries.
    entry["target_max_health_sensitive"] = True
    return entry


# Temper: "Ornn's and allies' immobilizing effects or silences against
# Brittle enemies will consume the debuff to deal bonus magic damage equal
# to 9% : 17.94% (based on Ornn's level) of the target's maximum health".
# The two endpoints are read out of that sentence rather than copied.
_TEMPER_EFFECT_MARKER = "Innate - Temper"
_TEMPER_CONSUME_RE = re.compile(
    r"bonus magic damage equal to\s+(?P<low>\d+(?:\.\d+)?)\s*%\s*:\s*"
    r"(?P<high>\d+(?:\.\d+)?)\s*%\s*\(based on Ornn's level\)\s*"
    r"of the target's\s+maximum health",
    re.IGNORECASE,
)
# HARDCODED, and only as the drift guard on the prose above: the game file
# (CommunityDragon ``characters/ornn/ornn.bin.json``, ``OrnnWAbility`` ->
# ``mSpellCalculations.BrittlePercentMaxHPCalc``) interpolates
# ``mStartValue`` 0.09 to ``mEndValue`` 0.17 with a bare
# ``ByCharLevelInterpolationCalculationPart``, i.e. across levels 1-18.
# That slope extrapolated to today's level cap of 20 is what makes the
# wiki's second endpoint 17.94% rather than 17%, so the prose endpoints
# span 1..MAX_LEVEL and reproduce the game file's level-18 value to well
# inside the tolerance below.  Verify both on patch updates.
_TEMPER_GAME_FILE_PERCENT_AT_1 = 9.0
_TEMPER_GAME_FILE_PERCENT_AT_18 = 17.0
_TEMPER_GAME_FILE_TOP_LEVEL = 18
_TEMPER_PERCENT_TOLERANCE = 0.01


def _temper_consume_percent(passive: dict[str, Any] | None, level: int) -> float:
    """Brittle's consume share of the target's maximum health at *level*.

    The two endpoints come from the cached Temper prose and are read as the
    level-1 and level-``MAX_LEVEL`` values of one linear ramp; the game
    file's own level-18 value is asserted against that ramp so a patch that
    moves either source raises instead of pricing a stale rider.
    """
    descriptions = [
        str(effect.get("description") or "")
        for effect in (passive or {}).get("effects") or []
    ]
    match = next(
        filter(
            None,
            (
                _TEMPER_CONSUME_RE.search(text)
                for text in descriptions
                if _TEMPER_EFFECT_MARKER in text
            ),
        ),
        None,
    )
    if match is None:
        raise ValueError(
            "Ornn P (Temper): the cached passive description no longer states "
            "the Brittle consume's '<low>% : <high>% (based on Ornn's level) "
            "of the target's maximum health' — the rider cannot be sourced"
        )
    low, high = float(match.group("low")), float(match.group("high"))
    span = (high - low) / (MAX_LEVEL - 1)
    at_18 = low + span * (_TEMPER_GAME_FILE_TOP_LEVEL - 1)
    if (
        abs(low - _TEMPER_GAME_FILE_PERCENT_AT_1) > _TEMPER_PERCENT_TOLERANCE
        or abs(at_18 - _TEMPER_GAME_FILE_PERCENT_AT_18) > _TEMPER_PERCENT_TOLERANCE
    ):
        raise ValueError(
            f"Ornn P (Temper) drifted: the cached prose ramp {low:g}% -> "
            f"{high:g}% gives {at_18:.4g}% at level 18, and the game file's "
            f"BrittlePercentMaxHPCalc interpolates "
            f"{_TEMPER_GAME_FILE_PERCENT_AT_1:g}% -> "
            f"{_TEMPER_GAME_FILE_PERCENT_AT_18:g}%"
        )
    return low + span * (min(max(level, 1), MAX_LEVEL) - 1)


def _temper_consume(ctx: SlotCtx, consume_time: float) -> dict[str, Any]:
    """The one Brittle consume a two-pass Call of the Forge God performs.

    R's first pass "applies Brittle to targets for 3 seconds"; its recast
    pass 1.25 seconds later "knocks them up and stuns them", which is the
    immobilise Temper consumes on — inside the debuff's own window, so the
    consume is a property of the cast rather than of the surrounding
    rotation.  Bellows Breath's final gout applies the same debuff and only
    refreshes it, and Brittle does not stack, so a W beforehand adds no
    second consume.
    """
    passive = ctx.ability("P")
    percent = _temper_consume_percent(passive, ctx.level)
    damage = percent / 100.0 * ctx.target_stat("target_max_health")
    # The receipt is published under the passive SLOT's cached name, which
    # is the whole innate's ("Living Forge"), qualified by the one innate
    # this row prices — the Kai'Sa "Second Skin (Plasma)" precedent.
    return post_hit_proc_row(
        name=f"{passive['name']} (Temper)",
        breakdown_key="passive_temper_brittle",
        parts=(DamagePart("magic", damage, time_offset=consume_time),),
        detail=(
            f"the recast pass immobilises a Brittle target and consumes the "
            f"debuff for {percent:.2f}% of maximum health"
        ),
    )


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
    if passes == 2:
        # Only the recast pass immobilises, so only a two-pass cast reaches
        # Temper's consume; one pass slows and leaves the debuff standing.
        entry["post_hit_proc"] = _temper_consume(ctx, _R_RECAST_DELAY)
        entry["target_max_health_sensitive"] = True
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
    "Call of the Forge God defaults to both sourced passes; one pass is an explicit option, and Temper's Brittle consume rides the second pass, so a one-pass fight prices no consume.",
    "Living Forge and Master Craftsman are item/state systems, not direct enemy damage.",
    "P (Temper) is modeled through Call of the Forge God: the recast pass "
    "immobilises a target the first pass made Brittle, so every two-pass R "
    "consumes the debuff exactly once for 9% : 17.94% (by Ornn's level, "
    "cached passive prose) of the target's maximum health, published as the "
    "passive's own breakdown row.",
    "The consume's other sourced triggers are not priced: Searing Charge's "
    "terrain-collision shockwave (the collision itself is unmodeled), "
    "Volcanic Rupture's magma pillar knock-aside (the pillar deals no "
    "damage and is not on the cast timeline), and allies' immobilises or "
    "silences (no ally crowd-control timeline exists). Each would consume a "
    "live Brittle in game; the modeled kit therefore prices a floor, not a "
    "ceiling.",
    "The consume's 200 : 500 monster cap and Temper's empowered "
    "basic-attack knock-back are outside a champion-target fight: the cap "
    "applies to monsters only, and the knock-back adds no damage.",
]

SOURCES = load_champion_sources("Ornn")

# P prices Temper's consume through R's ``post_hit_proc`` and holds no
# ``SLOTS`` entry of its own, so the derived reading (``out_of_scope``)
# under-reports it.  The proc rides the recast pass, so at ``r_passes=1``
# (a non-default option) P emits nothing and the label overstates.
MODULE_COVERAGE = coverage()
COVERAGE_CHANNELS = {"P": ("post_hit_proc",)}
