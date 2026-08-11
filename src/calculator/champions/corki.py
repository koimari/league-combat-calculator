"""Corki — slot map for the archetype engine.

Why each slot is non-generic:
- P (Hextech Munitions) has NO leveling data at all — ``effects[0]``
  carries an empty ``leveling`` list, so the generic path emitted
  nothing. The 20% total-AD true damage on every basic attack lives in
  the description text alone and is a tested constant here (the Gnar
  Mega-form precedent). It is emitted as ``basic_attack_true_ratio``
  (and ``spellblade_bonus_true_ratio`` for the item rider) because it
  must ride the swing's PRE-mitigation damage: that is what makes it
  crit-multiplied, and it is what the wiki's spellblade special case
  measures too.
- Q (Phosphorus Bomb) is the one slot the generic path already read
  correctly; it is pinned here so the slot map is the whole kit.
- W (Valkyrie) keeps its damage in ``effects[1]`` (``effects[0]`` is the
  dash) and the classifier picks "Magic Damage Per Tick". The modeled
  hit is ONE blazing patch — the JSON's "Total Magic Damage" spread over
  5 ticks in 2.5s — scaled by how long the target stays in it, and it
  must declare ``dot_duration`` so item burns keep refreshing through
  the patch instead of ending at the cast.
- E (Gatling Gun) needs "Total Physical Damage" (16 ticks over 4s) for
  the same reason, plus a flat armor AND magic-resist shred the generic
  path cannot express at all: one stack per tick to a cap of 4.
- R (Missile Barrage) is a charge/ammo ultimate with a cadence: stored
  charges plus recharge (accelerated by basic attacks) decide how many
  missiles fly, and every third one is a Big One at double damage. The
  generic path read the 2s inter-cast cooldown as the ability cooldown
  and never saw the Big One entry (``effects[3]``).

Shred rule, deliberately deviating from Kog'Maw Q
-------------------------------------------------
The engine's standing rule is "a shred never boosts the ability that
applied it" — written for instant single-hit shreds. Gatling Gun applies
its stacks one per tick across four seconds, so its own LATER ticks do
land against the stacks its earlier ticks applied. Tick k is priced
against k-1 stacks (the per-tick reading of the same rule) and ticks 5
onward against the full four. Do not "fix" this back to a single
post-ability application.

All values come from the champion JSON except the constants below.
"""

import math
from typing import Any

from ..ability_spec import DamagePart
from ..damage import effective_cooldown
from .engine import ONHIT, SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cast_time,
    extract_cooldown,
    extract_named,
    extract_recharge,
    extract_value,
    simple_damage,
)

# HARDCODED: verify on patch updates — wiki values with no JSON home.
# https://wiki.leagueoflegends.com/en-us/Corki
# P: "Corki's basic attacks deal bonus true damage equal to 20% AD. This
# damage is affected by critical strike modifiers." The passive's
# leveling list is empty, so nothing in the JSON carries this ratio.
_PASSIVE_TRUE_AD_RATIO = 0.20
# W: "Each patch lasts 2.5 seconds" and ticks "every 0.5 seconds" -> 5
# ticks; E: "for 4 seconds ... every 0.25 seconds" -> 16 ticks. Both tick
# counts are also exactly Total / Per-Tick in the JSON (test-locked).
_W_TICKS = 5
_W_DURATION = 2.5
_E_TICKS = 16
_E_DURATION = 4.0
# The engine authors per-tick damage events from these sourced cadences.
_W_TICK_INTERVAL = _W_DURATION / _W_TICKS  # "every 0.5 seconds"
_E_TICK_INTERVAL = _E_DURATION / _E_TICKS  # "every 0.25 seconds"
# Each Gatling stack lasts 2s but REFRESHES on every tick, so the
# shred is up until 2s after the last one ("applying a stack ... for
# 2 seconds, refreshing with subsequent hits").
_E_SHRED_LINGER = 2.0
# E: "applying a stack ... stacking up to 4 times", one per tick.
_E_MAX_SHRED_STACKS = 4
# R: "up to a maximum of 4" charges; "every third missile ... is a Big
# One"; basic attacks on-hit against champions cut 2-6s (scaling with
# critical strike chance) off the remaining recharge.
_R_MAX_CHARGES = 4
_R_BIG_ONE_CYCLE = 3
_R_AUTO_RECHARGE_MIN = 2.0
_R_AUTO_RECHARGE_MAX = 6.0


def _fraction_option(ctx: SlotCtx, key: str) -> float:
    """Read a 0..1 uptime option, clamped (default: the whole duration)."""
    return min(max(float(ctx.option(key)), 0.0), 1.0)


def _ticks_at_uptime(ticks: int, uptime: float) -> int:
    """Ticks landed over *uptime* of a DoT, rounding half up.

    ``round()`` is banker's rounding — it would drop the tick at exactly
    half a duration while keeping it just above and below.
    """
    return math.floor(ticks * uptime + 0.5)


def _hextech_munitions(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: every basic attack deals 20% of total AD again as true damage.

    Declared as a share of the attack's PRE-MITIGATION damage rather
    than a flat number, so a critical strike multiplies the true
    instance exactly as it multiplies the physical one — and so the
    identical wiki wording for the spellblade special case is the
    identical constant.
    """
    ability = ctx.ability()
    if ability is None:
        return None

    return {
        "name": ability.get("name", "Hextech Munitions"),
        "damage_type": "true",
        "total_raw": 0.0,  # priced per attack by the fight engine
        "parts": (),
        "basic_attack_true_ratio": _PASSIVE_TRUE_AD_RATIO,
        # The wiki special-cases spellblade into the same passive: the
        # proc pays the ratio of ITS pre-mitigation damage, on top.
        "spellblade_bonus_true_ratio": _PASSIVE_TRUE_AD_RATIO,
    }


_hextech_munitions.phase = ONHIT


def _valkyrie(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: one blazing patch's 5 ticks, scaled by the target's patch uptime."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    uptime = _fraction_option(ctx, "w_patch_uptime")
    ticks = _ticks_at_uptime(_W_TICKS, uptime)
    per_tick = (
        extract_named(ability, "Total Magic Damage", rank, ctx.stats, ctx.target)
        / _W_TICKS
    )

    entry = damage_entry(
        ability.get("name", "Valkyrie"),
        rank,
        extract_cooldown(ability, rank),
        per_tick * ticks,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            per_tick,
            count=ticks,
            time_offset=_W_TICK_INTERVAL,
            hit_interval=_W_TICK_INTERVAL,
        ),
    )
    entry["dot_duration"] = _W_DURATION * uptime
    entry["dot_tick_interval"] = _W_TICK_INTERVAL
    entry["detail"] = f"{ticks} tick(s) of one blazing patch over {_W_DURATION:g}s"
    return entry


def _gatling_gun(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: 16 ticks in a cone, ramping a flat armor/MR shred one per tick.

    The ticks are one part; the engine's ``stacks`` ramp lands a stack
    after each of the first four HITS of it.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    uptime = _fraction_option(ctx, "e_cone_uptime")
    ticks = _ticks_at_uptime(_E_TICKS, uptime)
    per_tick = (
        extract_named(ability, "Total Physical Damage", rank, ctx.stats, ctx.target)
        / _E_TICKS
    )
    stacks = min(_E_MAX_SHRED_STACKS, ticks)

    entry: dict[str, Any] = {
        "name": ability.get("name", "Gatling Gun"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "physical",
        "total_raw": per_tick * ticks,
        "parts": (
            (
                DamagePart(
                    "physical",
                    per_tick,
                    count=ticks,
                    time_offset=_E_TICK_INTERVAL,
                    hit_interval=_E_TICK_INTERVAL,
                ),
            )
            if ticks
            else ()
        ),
        "dot_duration": _E_DURATION * uptime,
        "dot_tick_interval": _E_TICK_INTERVAL,
    }
    if stacks > 0:
        shred = extract_value(ability, "Resistances Reduction Per Stack", rank) * stacks
        entry["target_debuff"] = {
            "armor_reduction_flat": shred,
            "mr_reduction_flat": shred,
            "stacks": stacks,
            "duration": _E_DURATION + _E_SHRED_LINGER,
        }
        entry["detail"] = (
            f"{ticks} tick(s) over {_E_DURATION:g}s; shreds {shred:g} armor and "
            f"magic resist over {stacks} stack(s), one per tick"
        )
    return entry


def _missile_count(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> tuple[int, str]:
    """Missiles fired this fight, and the prose explaining the count.

    Per-cast mode (one rotation, or a direct parse call with no injected
    fight window) fires the stored charges — the burst dumps ammo. A
    timed fight adds the charges that come back inside the window: the
    20s recharge shortened by ability haste, with every basic attack
    on-hit knocking 2-6s (scaling with critical strike chance) off the
    remaining timer. The total is capped by how often Corki can pull the
    trigger — the 2s inter-cast cooldown plus the cast time.
    """
    charges = int(ctx.options.get("r_starting_charges", _R_MAX_CHARGES))
    charges = min(max(charges, 0), _R_MAX_CHARGES)

    duration = ctx.options.get("fight_duration_seconds")
    if duration is None:
        return charges, f"{charges} stored charge(s) fired"
    duration = float(duration)

    haste = ctx.stat("ability_haste")
    recharge = effective_cooldown(extract_recharge(ability, rank), haste)
    autos = math.floor(
        ctx.stat("attack_speed") * float(ctx.option("auto_attack_uptime")) * duration
    )
    crit_chance = min(ctx.stat("critical_strike_chance") / 100.0, 1.0)
    per_auto = _R_AUTO_RECHARGE_MIN + crit_chance * (
        _R_AUTO_RECHARGE_MAX - _R_AUTO_RECHARGE_MIN
    )
    recharged = int((duration + autos * per_auto) // recharge) if recharge > 0 else 0

    between_casts = effective_cooldown(
        extract_cooldown(ability, rank), haste
    ) + extract_cast_time(ability)
    trigger_cap = (
        1 + int(duration / between_casts) if between_casts > 0 else charges + recharged
    )
    missiles = max(0, min(charges + recharged, trigger_cap))
    return missiles, (
        f"{charges} stored + {recharged} recharged in {duration:g}s "
        f"({autos} auto(s) x {per_auto:.1f}s off the timer); the "
        f"{between_casts:.1f}s trigger cycle fits {trigger_cap}"
    )


def _missile_barrage(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: the fight's missiles, with every third one a double-damage Big One.

    Per-missile damage is reported per missile (the charge-ability rule);
    the counts live on the parts because the fight engine casts an
    ultimate exactly once, so it never repeats them itself.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    regular = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    big_one = extract_named(
        ability, "Big One Physical Damage", rank, ctx.stats, ctx.target
    )

    missiles, ammo_detail = _missile_count(ctx, ability, rank)
    cycle = min(max(int(ctx.option("r_big_one_cycle_position")), 0), 2)
    big_ones = (cycle + missiles) // _R_BIG_ONE_CYCLE

    parts = tuple(
        DamagePart("physical", amount, count=count)
        for amount, count in ((regular, missiles - big_ones), (big_one, big_ones))
        if count > 0
    )
    return {
        "name": ability.get("name", "Missile Barrage"),
        "rank": rank,
        # The recharge, not the 2s inter-cast timer, is what limits
        # sustained use (the Amumu charge-ability rule).
        "cooldown": extract_recharge(ability, rank),
        "damage_type": "physical",
        "total_raw": regular * (missiles - big_ones) + big_one * big_ones,
        "parts": parts,
        # Each missile is its own cast for per-cast item procs (Muramana).
        "cast_instances": missiles,
        "detail": (f"{missiles} missile(s) incl. {big_ones} Big One(s): {ammo_detail}"),
    }


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "r_starting_charges",
        "type": "int",
        "default": _R_MAX_CHARGES,
        "label": "R charges stored at fight start",
        "min": 0,
        "max": _R_MAX_CHARGES,
    },
    {
        "key": "r_big_one_cycle_position",
        "type": "int",
        "default": 0,
        "label": "Missiles already fired toward the next Big One",
        "min": 0,
        "max": _R_BIG_ONE_CYCLE - 1,
    },
    {
        "key": "w_patch_uptime",
        "type": "float",
        "default": 1.0,
        "label": "Fraction of W's 2.5s patch duration the target stays in it",
        "min": 0.0,
        "max": 1.0,
        "step": 0.1,
    },
    {
        "key": "e_cone_uptime",
        "type": "float",
        "default": 1.0,
        "label": "Fraction of E's 4s duration the target stays in the cone",
        "min": 0.0,
        "max": 1.0,
        "step": 0.1,
    },
]

ASSUMPTIONS = [
    "Passive true damage (20% of total AD) applies to every basic attack "
    "and is multiplied by critical strike modifiers on a crit",
    "Spellblade procs deal an extra 20% of their pre-mitigation damage as "
    "true damage (the wiki's Hextech Munitions special case)",
    "Runaan's Hurricane bolts get the same 20% true-damage rider in-game, "
    "but the bolts only hit OTHER enemies — this single-target model "
    "values neither the bolts nor their rider",
    "W: the target is caught by ONE blazing patch, taking all 5 ticks over "
    "2.5s (overlapping patches from a longer dash are not modeled)",
    "E: the target stays in the cone for all 16 ticks over 4s by default; "
    "E is not a channel, so autos continue normally during it",
    "E's resistance shred ramps one stack per tick to a maximum of 4, and "
    "E's own later ticks benefit from the stacks its earlier ticks applied",
    "E shreds armor and magic resist by a flat amount that may take the "
    "target's resistances below zero, where they amplify damage",
    "R starts the fight with full ammo (4 charges) and a fresh Big One "
    "cycle; every third missile fired is a Big One",
    "R in one-rotation mode dumps ALL stored charges as the burst, which "
    "takes ~6s of 2s inter-cast lockouts in game — one-rotation R is the "
    "full ammo dump, not a 5-second window, so it can exceed a short "
    "timed fight's missile count",
    "R in a timed fight adds the charges that recharge inside the window "
    "and caps the barrage at the 2s inter-cast cooldown plus cast time",
    "R recharge is accelerated by basic attacks on-hit against champions "
    "(2-6s per attack, scaling with critical strike chance); every auto is "
    "credited, though in game the reduction is wasted while at 4 charges",
    "The whole barrage occupies the shared cast timeline as a single "
    "0.175s cast, and counts as ONE cast toward the spellblade proc "
    "budget (each missile does proc per-cast effects like Muramana)",
]

SLOTS = {
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "W": _valkyrie,
    "E": _gatling_gun,
    "R": _missile_barrage,
    "P": _hextech_munitions,
}

parse_abilities = build_parser(SLOTS, "Corki")


# Authoritative review metadata (issue #161).
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Corki",
        "revision_id": 4047300,
        "revision_timestamp": "2026-07-29T13:12:25Z",
    }
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
