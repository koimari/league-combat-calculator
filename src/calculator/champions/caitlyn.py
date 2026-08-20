"""Caitlyn — slot map for the archetype engine.

Why each slot is non-generic:
- P (Headshot) has ZERO effects/leveling data in the JSON — the
  every-6th-attack rider formula is hand-authored from the wiki template
  below: ``bonus = total AD x (level bracket ratio + crit chance x
  (1 + bonus crit damage))``. The crit component is an ADDITIVE AD
  ratio, so the flat rider is computed here from the parse context's
  crit stats — never via the engine's multiplicative
  ``crit_effectiveness`` formula, which is wrong below level 13.
  The slot counts the fight's headshot procs: natural cadence over the
  timed auto stream, one conversion per E cast, and exactly one trap
  headshot (which alone takes W's damage increase). In one-rotation
  mode (no auto stream) the granted headshots are the basic attacks the
  combo forces, so each row carries the expected-crit base swing plus
  the rider (the Blitzcrank E / Vayne Q one-rotation precedent).
- W (Yordle Snap Trap) deals no damage itself, but the generic
  classifier misread its "Headshot Damage Increase" leveling entry as a
  standalone magic nuke. E4 treats the trap as a summoned unit: the W
  slot is an explicit zero-damage utility row (root 1.5s + reveal 3s)
  whose damage contribution is the trap Headshot — priced by P with
  this slot's "Headshot Damage Increase". The ``w_traps`` option
  (default 1) is the player-controlled number of traps the enemy steps
  on; each sprung trap grants one trap Headshot (P multiplies).
- R (Ace in the Hole) reads the JSON's "Physical damage" (lowercase d)
  and adds the wiki-prose crit scaling: up to +30% (+IE) with crit
  chance — exactly the engine's ``crit_effectiveness=0.3`` part formula
  (the Akshan R pattern).
- Q (Piltover Peacemaker) pins the primary "Physical Damage" attribute;
  the JSON also carries a "Reduced Damage" secondary-target entry the
  single-target model must never pick up.
- E (90 Caliber Net) pins "Magic Damage"; its headshot conversion is
  counted by P.

The parse context's ``crit_damage_bonus`` key (the build's crit damage
above the 2.0 base, e.g. Infinity Edge's +0.3) is injected by
``pipeline.run_fight``; direct parse calls without it price headshots
at base crit damage.
"""

import math
from typing import Any

from ..ability_spec import DamagePart
from ..damage import effective_cooldown
from .engine import SlotCtx, build_parser
from .slotlib import (
    extract_cooldown,
    extract_named,
    extract_recharge,
    extract_value,
    simple_damage,
)

# HARDCODED: verify on patch updates — wiki values with no JSON home
# (the P entry has no leveling data; R's crit scaling is prose).
# https://wiki.leagueoflegends.com/en-us/Caitlyn
_HEADSHOT_CADENCE = 6  # every 6th basic attack is a Headshot
# Headshot total-AD ratio brackets: 60/80/100% at levels 1/7/13
# (wiki template ``{{pp|key=%|60 to 100 for 3|1 to 13}}``).
_HEADSHOT_LEVEL_RATIOS = ((13, 1.00), (7, 0.80), (1, 0.60))
# R's total damage is increased by 0-30% (+ bonus crit damage) based on
# crit chance — the engine's part-level crit formula.
_R_CRIT_EFFECTIVENESS = 0.3


def _headshot_level_ratio(level: int) -> float:
    """Headshot's level-bracket AD ratio: 0.60 / 0.80 / 1.00 at 1/7/13."""
    for min_level, ratio in _HEADSHOT_LEVEL_RATIOS:
        if level >= min_level:
            return ratio
    return _HEADSHOT_LEVEL_RATIOS[-1][1]


def _trap_headshot_increase(ctx: SlotCtx) -> float | None:
    """W's flat damage increase on a trap headshot; None = no trap.

    With W unranked there is no trap to step on, so no trap headshot at
    all (not a zero-increase one).
    """
    ability = ctx.ability("W")
    if ability is None or ctx.rank_for("W") < 1:
        return None
    return extract_named(
        ability, "Headshot Damage Increase", ctx.rank_for("W"), ctx.stats, ctx.target
    )


def _trap_grants(ctx: SlotCtx) -> int:
    """How many Yordle Snap Traps spring this fight (0 = none).

    ``w_traps`` (default 1) is the player-controlled count of traps the
    enemy steps on, capped by W's "Maximum Number of Traps" at rank
    (3/3/4/4/5).  Each sprung trap grants exactly one trap Headshot.
    An autos-only fight never casts W, so no trap is ever laid.
    """
    ability = ctx.ability("W")
    if ability is None or ctx.rank_for("W") < 1:
        return 0
    if ctx.option("auto_attacks_only"):
        return 0
    rank = ctx.rank_for("W")
    cap = max(1, int(extract_value(ability, "Maximum Number of Traps", rank) or 5))
    return min(max(int(ctx.option("w_traps")), 0), cap)


def _e_cast_count(ctx: SlotCtx, duration: float) -> int:
    """E casts over a timed fight: t=0 then on cooldown (rotation's count).

    An autos-only fight casts nothing, so it grants no headshots.
    """
    ability = ctx.ability("E")
    rank = ctx.rank_for("E")
    if ability is None or rank < 1 or ctx.option("auto_attacks_only"):
        return 0
    haste = ctx.stat("ability_haste") + ctx.stat("basic_ability_haste")
    cd = effective_cooldown(extract_cooldown(ability, rank), haste)
    return 1 + int(duration / cd) if cd > 0 else 1


def _headshot_counts(ctx: SlotCtx, trap_grants: int) -> tuple[int, int, int, int, str]:
    """Count the fight's headshots: (trap, E-granted, cadence, swings, detail).

    Timed fights with an auto stream: headshots CONVERT autos already in
    the stream, so total conversions are capped by the auto count — the
    trap first (largest hit), then E grants, then natural cadence;
    ``swings`` is 0 because the converted autos already swing in the
    auto stream.
    No auto stream (one-rotation mode, or a timed fight at zero auto
    uptime): each granted headshot is a forced basic attack — ``swings``
    counts them (the engine's empowers_next_auto rule).

    ``p_pre_stacks`` (0-5, default 0) is the explicit pre-stacked Count:
    a headshot is on the auto that would land the 5th stack, so pre-stacked
    stacks advance the cadence — heads = (pre_stacks + autos) // 6.
    """
    pre_stacks = min(max(int(ctx.option("p_pre_stacks")), 0), 5)
    duration = ctx.options.get("fight_duration_seconds")
    if duration is not None:
        uptime = float(ctx.option("auto_attack_uptime"))
        num_autos = math.floor(ctx.stat("attack_speed") * uptime * duration)
        if num_autos > 0:
            remaining = num_autos
            trap_used = min(trap_grants, remaining)
            remaining -= trap_used
            e_used = min(_e_cast_count(ctx, float(duration)), remaining)
            remaining -= e_used
            cadence_used = min((pre_stacks + num_autos) // _HEADSHOT_CADENCE, remaining)
            detail = (
                f"{trap_used + e_used + cadence_used} headshot(s) over "
                f"{float(duration):g}s: {cadence_used} cadence + {e_used} "
                f"E-granted + {trap_used} trap"
            )
            return trap_used, e_used, cadence_used, 0, detail
        trap_used = trap_grants
        e_used = _e_cast_count(ctx, float(duration))
        swings = trap_used + e_used
        detail = (
            f"{swings} forced headshot attack(s) over {float(duration):g}s: "
            f"{e_used} E-granted + {trap_used} trap; each includes the "
            f"base swing"
        )
        return trap_used, e_used, 0, swings, detail

    trap_used = trap_grants
    e_used = 1 if ctx.rank_for("E") >= 1 else 0
    swings = trap_used + e_used  # the combo forces these basic attacks
    detail = (
        f"{swings} forced headshot attack(s): {e_used} E-granted + "
        f"{trap_used} trap; each row includes the base swing"
    )
    return trap_used, e_used, 0, swings, detail


def _headshot(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: every-6th-auto rider + one headshot per E cast + one trap headshot.

    ``_headshot_counts`` decides how many headshots land (and whether
    they carry their own basic-attack swing); this prices them. The
    rider bonus is the wiki formula — an ADDITIVE total-AD ratio,
    crit-scaled; the rider itself cannot crit.
    """
    ability = ctx.ability()
    if ability is None:
        return None

    total_ad = ctx.stat("attack_damage")
    crit_chance = min(ctx.stat("critical_strike_chance") / 100.0, 1.0)
    bonus_crit_damage = ctx.stat("crit_damage_bonus")
    bonus = total_ad * (
        _headshot_level_ratio(ctx.level) + crit_chance * (1.0 + bonus_crit_damage)
    )
    trap_increase = _trap_headshot_increase(ctx)
    trap_grants = _trap_grants(ctx)

    trap_used, e_used, cadence_used, swings, detail = _headshot_counts(
        ctx, 0 if trap_increase is None else trap_grants
    )
    if trap_used + e_used + cadence_used == 0:
        return None

    # Expected-crit basic attack, matching the fight engine's
    # crit_effectiveness=1.0 swing (Blitzcrank E precedent). Every part
    # is basic damage in-game (the swing IS a basic attack; the Headshot
    # rider is classified basic damage), so Hexoptics-style basic-damage
    # amplifiers apply.
    swing = total_ad * (1.0 + crit_chance * (1.0 + bonus_crit_damage))
    parts = tuple(
        DamagePart("physical", amount, count=count, basic_damage=True)
        for amount, count in (
            (swing, swings),
            (bonus, e_used + cadence_used),
            (bonus + (trap_increase or 0.0), trap_used),
        )
        if count > 0
    )
    return {
        "name": ability.get("name", "Headshot"),
        "damage_type": "physical",
        "total_raw": sum(part.amount * part.count for part in parts),
        "parts": parts,
        "proc_count": 1,
        "detail": detail,
    }


_ace_base = simple_damage(attr="Physical damage", dmg_type="physical")


def _ace_in_the_hole(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: JSON damage with the 0.3-effectiveness crit scaling stamped on."""
    entry = _ace_base(ctx)
    if entry is not None:
        entry["parts"] = (
            DamagePart(
                "physical",
                entry["total_raw"],
                crit_effectiveness=_R_CRIT_EFFECTIVENESS,
            ),
        )
        # One homing bullet on "the first enemy champion it hits" — one
        # part, one hit, which carries R's reviewed control answer into
        # the event ledger.
        entry["event_order_certified"] = "single_hit"
    return entry


def _yordle_snap_trap(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: sprung Yordle Snap Trap — a summoned-trap utility row.

    The trap itself deals no damage: it roots (1.5s) and reveals (3s),
    and the damage it contributes is the trap Headshot — priced by the
    passive row with this slot's "Headshot Damage Increase".  The row
    documents the summon state (how many traps spring via ``w_traps``)
    on W's charge recharge rate; it never double-counts the passive.
    """
    ability = ctx.ability("W")
    if ability is None or ctx.rank_for("W") < 1:
        return None
    rank = ctx.rank_for("W")
    traps = _trap_grants(ctx)
    if traps <= 0:
        return None
    return {
        "name": ability.get("name", "Yordle Snap Trap"),
        "rank": rank,
        "cooldown": extract_recharge(ability, rank),
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": (
            f"{traps} sprung Yordle Snap Trap(s): root 1.5s + reveal 3s; "
            "each grants one trap Headshot whose W damage increase is "
            "priced by the passive row (the trap deals no direct damage)."
        ),
    }


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "p_pre_stacks",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 5,
        "label": "Pre-stacked Headshot Count stacks",
    },
    {
        "key": "w_traps",
        "type": "int",
        "default": 1,
        "min": 0,
        "max": 5,
        "label": "Sprung Yordle Snap Traps",
    },
]

ASSUMPTIONS = [
    "Headshot is a 5-stack Count system: attacks generate Count stacks "
    "(cap 5, doubled in brush) and the auto that would land the 5th "
    "stack consumes them all to become a Headshot — every 6th attack "
    "out of brush; p_pre_stacks advances that cadence",
    "Brush doubling is not modeled (out-of-brush stacking)",
    "Each sprung W trap grants exactly one trap headshot with W's damage "
    "increase; w_traps (default 1, capped by W's maximum traps at rank) "
    "is the player-controlled number of traps the enemy steps on; with "
    "W unranked (or w_traps=0) there is no trap headshot",
    "Each E cast grants one additional Headshot (no W bonus); granted "
    "headshots convert existing autos rather than adding attacks — with "
    "no auto stream (one-rotation mode, or auto attacks disabled) they "
    "are the forced basic attacks themselves (swing + headshot)",
    "An autos-only fight casts neither E nor W, so only the every-6th "
    "cadence lands (the pipeline states this with the auto_attacks_only "
    "reserved option)",
    "Headshot (swing and rider) is basic damage: basic-damage "
    "amplifiers (Hexoptics C44) apply to it",
    "Q assumes the target is hit first (full damage; the 60% "
    "secondary-target values are not modeled)",
    "R is assumed to hit (allied body-block not modeled); the Headshot "
    "vs non-champions (110% AD) is not modeled — the target is a champion",
    "Headshot bonus applies after the auto's own crit roll; the bonus "
    "itself cannot crit but scales with crit chance and bonus crit damage",
    "W (Yordle Snap Trap) is a summoned trap with no direct damage: the "
    "W row reports the sprung-trap count on the charge recharge rate, "
    "and the trap's damage contribution is the trap Headshot priced by "
    "the passive row (root 1.5s + reveal 3s are utility).",
]

SLOTS = {
    # Each of these is one shot on one target — the piercing bolt's first
    # enemy, the net's first enemy — so one part and one hit, which is the
    # certification that carries their reviewed control into the ledger.
    "Q": simple_damage(
        attr="Physical Damage",
        dmg_type="physical",
        event_order_certified="single_hit",
    ),
    "W": _yordle_snap_trap,
    "E": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "R": _ace_in_the_hole,
    "P": _headshot,
}

# Reviewed crowd control, read from the cached kit.  Q (Piltover
# Peacemaker) "deals physical damage to the first enemy it passes
# through" with no control clause.  E (90 Caliber Net) "deals magic
# damage to the first enemy hit and slows them by 50% for 1 second".  R
# (Ace in the Hole) "deals physical damage to the first enemy champion it
# hits" and reveals, which is not control.  W is the trap row — its root
# is real, but the row prices the trap Headshot the passive owns, not a
# cast of Caitlyn's own, and P is that passive.
MODULE_CC = {"Q": "none", "E": "slow", "R": "none"}

parse_abilities = build_parser(SLOTS, "Caitlyn", cc_kinds=MODULE_CC)


SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Caitlyn",
        "revision_id": 4022594,
        "revision_timestamp": "2026-05-27T00:34:15Z",
    }
]
