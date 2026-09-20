"""Caitlyn: slot map for the archetype engine.

P (Headshot) has no cached effects or leveling at all, so the every-sixth-attack
rider is authored from the wiki template below: total AD x (the level-bracket
ratio + crit chance x (1 + bonus crit damage)).  The crit component is an
ADDITIVE AD ratio computed here from the parse context's crit stats, never the
engine's multiplicative ``crit_effectiveness``, which is wrong below level 13.
The slot counts the fight's procs: the natural cadence over a timed auto stream,
one conversion per E cast, and exactly one trap headshot, which alone takes W's
damage increase.  With no auto stream the granted headshots are the swings the
combo forces, so each row carries the expected-crit base swing plus the rider.
``crit_damage_bonus``, the build's crit damage over the 2.0 base, is injected by
``pipeline.run_fight``; a direct parse call prices headshots at base crit damage.
W (Yordle Snap Trap) is a zero-damage utility row: its "Headshot Damage Increase"
row is not a nuke, and each of ``w_traps`` sprung traps grants one trap Headshot.
R (Ace in the Hole) reads "Physical damage" with a lowercase d and adds the
prose crit scaling as ``crit_effectiveness=0.3``.
Q pins the primary "Physical Damage"; its "Reduced Damage" secondary-target row
must never reach a single-target model.  E pins "Magic Damage".
"""

import math
from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from ..stat_formulas import effective_cooldown
from .charge_cadence import ChargeRule
from .engine import SlotCtx, build_parser
from .inputs import int_option
from .module_helpers import ability_slot, at_level, ranked_slot
from .shared_mechanics import reduced_secondary_hits
from .slot_control import extract_recharge
from .slot_entries import damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named, extract_value
from .slotlib import simple_damage
from .source_receipts import load_champion_sources

# HARDCODED: verify on patch updates — wiki values with no JSON home
# (the P entry has no leveling data; R's crit scaling is prose).
# https://wiki.leagueoflegends.com/en-us/Caitlyn
_HEADSHOT_CADENCE = 6  # every 6th basic attack is a Headshot
# Headshot total-AD ratio brackets: 60/80/100% at levels 1/7/13
# (wiki template ``{{pp|key=%|60 to 100 for 3|1 to 13}}``).
_HEADSHOT_LEVEL_RATIOS = ((13, 1.00), (7, 0.80), (1, 0.60))
# R's total damage is increased by 0-30% (+ bonus crit damage) based on
# crit chance — the engine's part-level crit formula.
_R_CRIT_EFFECTIVENESS = data_value(
    spell_object("Caitlyn", "CaitlynR"), "CriticalStrikeModifier"
)


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


@ability_slot()
def _headshot(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    """P: every-6th-auto rider + one headshot per E cast + one trap headshot.

    ``_headshot_counts`` decides how many headshots land (and whether
    they carry their own basic-attack swing); this prices them. The
    rider bonus is the wiki formula — an ADDITIVE total-AD ratio,
    crit-scaled; the rider itself cannot crit.
    """

    total_ad = ctx.stat("attack_damage")
    crit_chance = min(ctx.stat("critical_strike_chance") / 100.0, 1.0)
    bonus_crit_damage = ctx.stat("crit_damage_bonus")
    bonus = total_ad * (
        at_level(_HEADSHOT_LEVEL_RATIOS, ctx.level)
        + crit_chance * (1.0 + bonus_crit_damage)
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
        "name": ability_name(ability),
        "damage_type": "physical",
        "total_raw": sum(part.amount * part.count for part in parts),
        "parts": parts,
        "proc_count": 1,
        "detail": detail,
    }


@ranked_slot
def _piltover_peacemaker(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """Q: primary hit plus ``q_secondary_targets`` at the sourced 60% row.

    The cached prose: the shot "deals physical damage to the first enemy
    it passes through, after which it expands in width but deals only
    60% damage to enemies it hits thereafter" — the "Reduced Damage"
    row is exactly 60% of "Physical Damage" at every rank (flat and
    % AD).  Each secondary target selected via the declared
    ``q_secondary_targets`` champion option takes one reduced hit;
    traps-revealed enemies (full damage) are not distinguished.
    """

    return reduced_secondary_hits(
        ctx,
        ability,
        rank,
        dmg_type="physical",
        primary_row="Physical Damage",
        reduced_row="Reduced Damage",
        option="q_secondary_targets",
        lead="primary hit",
        noun="secondary target(s)",
    )


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
    return damage_entry(
        ability_name(ability),
        rank,
        extract_recharge(ability, rank),
        0.0,
        "magic",
        parts=(),
        detail=(
            f"{traps} sprung Yordle Snap Trap(s): root 1.5s + reveal 3s; "
            "each grants one trap Headshot whose W damage increase is "
            "priced by the passive row (the trap deals no direct damage)."
        ),
    )


OPTIONS: list[dict[str, Any]] = [
    int_option(
        "p_pre_stacks",
        0,
        minimum=0,
        maximum=5,
        label="Pre-stacked Headshot Count stacks",
        rotation={"role": "self_state", "slot": "P"},
    ),
    int_option(
        "w_traps",
        1,
        minimum=0,
        maximum=5,
        label="Sprung Yordle Snap Traps",
        rotation={"role": "self_state", "slot": "W"},
    ),
    int_option(
        "q_secondary_targets",
        0,
        minimum=0,
        maximum=5,
        label="Enemies the shot passes through beyond the first (each "
        "takes the sourced 60% Reduced Damage row)",
        rotation={"role": "irrelevant", "slot": "Q"},
    ),
]

ASSUMPTIONS = [
    "Headshot is a 5-stack Count: the auto that would land the 5th consumes them all, "
    "every 6th attack out of brush.",
    "Stacks double in brush, and p_pre_stacks advances that cadence.",
    "Brush doubling is not modeled (out-of-brush stacking)",
    "Each sprung W trap grants one trap headshot at W's damage increase.",
    "w_traps (default 1, capped by W's maximum at rank) is the player-controlled "
    "count; W unranked grants none.",
    "Each E cast grants one extra Headshot with no W bonus, converting an existing "
    "auto rather than adding one.",
    "With no auto stream they are forced basic attacks themselves, swing plus "
    "headshot.",
    "An autos-only fight casts neither E nor W, so only the every-6th cadence lands "
    "(auto_attacks_only).",
    "Headshot (swing and rider) is basic damage: basic-damage "
    "amplifiers (Hexoptics C44) apply to it",
    "Q prices the primary hit in full plus one sourced 60% Reduced Damage hit per "
    "q_secondary_targets (default 0).",
    "A target revealed by Yordle Snap Trap takes full damage (wiki note), which this "
    "row does not separate.",
    "R is assumed to hit: an allied body-block is not modeled, and the 110% AD "
    "non-champion Headshot never applies.",
    "The Headshot bonus lands after the auto's crit roll; it cannot crit but scales "
    "with crit chance and crit damage.",
    "W (Yordle Snap Trap) deals no direct damage: its row reports the sprung-trap "
    "count on the charge recharge rate.",
    "The trap's damage is the trap Headshot on the passive row; its 1.5s root and 3s "
    "reveal are utility.",
]

SLOTS = {
    # Q and E are each one shot on one target — the piercing bolt's first
    # enemy, the net's first enemy — so one part and one hit, which is the
    # certification that carries their reviewed control into the ledger.
    # Q's own parser states that per parse, since a widened bolt selected
    # through q_secondary_targets is more than one landing.
    "Q": _piltover_peacemaker,
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
MODULE_CC = {"Q": "none", "E": "slow", "R": "none", "P": "none", "W": "root"}


# What this module says about its charge slot (charge_cadence.py).
CHARGE_RULES = {
    "W": ChargeRule(
        why=(
            "W (Yordle Snap Trap) banks traps on its cached "
            "rechargeRate (10s at rank 5), which this slot already "
            "prices. A stock IS sourced, just not from the wiki: the "
            "binary's CaitlynW mMaxAmmo is 2/3/3/4/4/5/5 by rank, where "
            "no Maximum charges row and no stocking sentence exists. It "
            "is not spent here all the same, and for the Heimerdinger "
            "reason rather than an absent number: the trap stands and "
            "arms, this row prices no damage at the cast, and what binds "
            "is how many traps may hold at once, which neither source "
            "states."
        ),
        charges=1,
    )
}
parse_abilities = build_parser(
    SLOTS, "Caitlyn", cc_kinds=MODULE_CC, charge_rules=CHARGE_RULES
)


SOURCES = load_champion_sources("Caitlyn")
