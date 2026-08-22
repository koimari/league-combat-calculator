"""Kled — full-entry reviewed CP10.3 module.

Option keys consumed by the shared parser: "q_pull", "charge_fraction".

Skaarl the Cowardly Lizard (P): while mounted, damage dealt to the duo
is suffered by Skaarl, whose 400 : 1400 (based on level) base health is
the mounted pool (data/champions.json P "Bonus Damage" leveling row).
The dismount/remount cycle is a revive-boundary pattern (like Aatrox's
ghost atom) and is NOT implemented: the E8a grey-health primitive
authors no Skaarl heal, and the pool is documented here as a boundary.
W (Violent Tendencies) is the 4-attack empowered burst; its fourth-hit
bonus is modeled by the CP10.3 packet.  Q (Pocket Pistol, the dismounted
Q) applies Grievous Wounds: the e8-interactions worklist
(data/worklists/e8-interactions.json) lists the Pocket Pistol GW, and
the wound rides the module's Q damage receipts at the patch-wide
40%-for-3s constants (healing_reduction module).
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import CC_PER_PART, SlotCtx, build_parser
from .module_helpers import REVIEWED_MODULE_ASSUMPTIONS, no_damage
from .slotlib import (
    ability_name,
    ability_on_hit_entry,
    damage_entry,
    extract_cooldown,
    extract_named,
    simple_damage,
)
from .source_receipts import load_champion_sources
from .inputs import bool_option, float_option
from .module_contract import coverage

# Bear Trap on a Rope lands twice and the cache times the second hit: the
# trap "collides with the first enemy champion ... forming a tether
# between Kled and the target for 1.75 seconds", and "if it is not broken
# before then, Kled pulls the target 150 units toward him, deals physical
# damage and slows them for 2.5 seconds".  ``time_offset`` runs from the
# cast start, and the cache states no travel time for the trap itself, so
# the throw sits at the cast and the pull 1.75 seconds after it.
_Q_TETHER_SECONDS = 1.75


def _bear_trap(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: the trap's own hit, then the tether's pull hit 1.75s later."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    # Two cached rows share the name "Physical Damage" — the trap's
    # (30 : 130 + 60% bonus AD) and the pull's (60 : 260 + 120% bonus AD).
    # The first is the one a name lookup reaches, and the cached "Total
    # Physical Damage" row (90 : 390 + 180% bonus AD) is their sum, so the
    # pull reads as the difference without depending on effect order.
    impact = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    pulls = bool(ctx.options.get("q_pull", True))
    total = (
        extract_named(ability, "Total Physical Damage", rank, ctx.stats, ctx.target)
        if pulls
        else impact
    )
    parts = [DamagePart("physical", impact, time_offset=0.0, cc_kind="none")]
    if pulls:
        parts.append(
            DamagePart(
                "physical",
                total - impact,
                time_offset=_Q_TETHER_SECONDS,
                cc_kind="pull",
            )
        )
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = tuple(parts)
    entry["detail"] = "trap hit at the cast" + (
        f", then the tether's pull {_Q_TETHER_SECONDS:g}s later"
        if pulls
        else " (the tether is broken before it pulls)"
    )
    return entry


def _violent_tendencies(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    value = extract_named(
        ability, "Additional Physical Damage", rank, ctx.stats, ctx.target
    )
    result = ability_on_hit_entry(
        ability_name(ability),
        rank,
        "physical",
        {
            "name": "Violent Tendencies (first three attacks)",
            "damage_per_hit": 0.0,
            "damage_type": "physical",
        },
        0.0,
    )
    result["parts"] = (
        DamagePart("physical", value, basic_damage=True, time_offset=0.1),
    )
    result["total_raw"] = value
    result["empowers_next_auto"] = True
    result["target_max_health_sensitive"] = True
    result["detail"] = (
        "Fourth attack of the four-hit Violent Tendencies sequence; 150% "
        "attack speed is state."
    )
    return result


def _charge(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    fraction = max(0.0, min(1.0, float(ctx.option("charge_fraction"))))
    low = extract_named(ability, "Minimum Magic Damage", rank, ctx.stats, ctx.target)
    high = extract_named(ability, "Maximum Magic Damage", rank, ctx.stats, ctx.target)
    value = low + (high - low) * fraction
    return {
        "name": ability_name(ability),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": value,
        "parts": (DamagePart("magic", value, time_offset=0.5),),
        "target_max_health_sensitive": True,
        "detail": (
            f"Charge fraction {fraction:.2f}; shield and team movement are "
            "utility state."
        ),
    }


SLOTS = {
    "P": lambda ctx: no_damage(
        ctx,
        name="Skaarl the Cowardly Lizard",
        reason=(
            "Mounted/dismounted health pool, remount and damage cutoff are "
            "participant state."
        ),
    ),
    "Q": _bear_trap,
    "W": _violent_tendencies,
    "E": simple_damage(attr="Total Physical Damage", dmg_type="physical"),
    "R": _charge,
}
OPTIONS = [
    bool_option("q_pull", True, label="Bear Trap pull resolves"),
    float_option(
        "charge_fraction",
        1.0,
        minimum=0.0,
        maximum=1.0,
        label="Chaaaaaaaarge distance",
        step=0.25,
    ),
]
ASSUMPTIONS = list(REVIEWED_MODULE_ASSUMPTIONS)
SOURCES = load_champion_sources("Kled")
# Reviewed crowd control, read from the cached kit.  W (Violent
# Tendencies) is the empowered fourth attack, which "deal[s] additional
# physical damage" and nothing else.  R (Chaaaaaaaarge!!!) collides with
# the first champion in the path "to deal magic damage ... [and] knock
# them back 150 units".  P authors no damage part.
#
# Q's two hits do not control alike, so the answer is authored per part
# rather than per slot (see ``_bear_trap``): the thrown trap only reveals
# and tethers, and the pull 1.75 seconds later is the immobilize.
#
# E stays UNREVIEWED, so this kit keeps the coarse control-armed scan.
# Jousting's row is the Total of the first dash and the recast dash, and
# the cache gives the recast no instant: "Jousting can be recast after 0.5
# seconds of the first dash ending while the target is marked" states when
# the recast becomes *available*, not when it happens, and the dash whose
# ending it counts from has no cached duration.  Half a schedule is not a
# schedule, so the second dash stays folded into the first hit.
MODULE_CC = {"Q": CC_PER_PART, "W": "none", "R": "knockback"}

parse_abilities = build_parser(SLOTS, "Kled", cc_kinds=MODULE_CC)

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "Skaarl the Cowardly Lizard (P): the mounted duo's damage is suffered "
    "by Skaarl, whose 400 : 1400 (based on level) base health is the "
    "mounted pool (data/champions.json P 'Bonus Damage'); the "
    "dismount/remount cycle is a revive-boundary pattern (like Aatrox's "
    "ghost atom) and is not modeled — the E8a grey-health primitive "
    "authors no Skaarl heal.",
    "Q Grievous Wounds: REMOVED — Pocket Pistol's wound was deleted in "
    "V25.14 (the e8-interactions worklist entry is stale; the wiki cache "
    "carries no Grievous Wounds on either Q entry), so the module declares "
    "no wound source.",
    "Base movement speed and attack range are FORM-ATTRIBUTED, not stale: "
    "data/champions.json carries movespeed 305 / attackRange 250 (the "
    "DISMOUNTED row of the wiki's two-form stat box) while the 16.16 game "
    "file Characters/Kled/CharacterRecords/Root carries 345 / 125 (MOUNTED). "
    "The wiki's own P[1] text reconciles them exactly — dismounting reduces "
    "movement speed 'by 40 to 305' (345 - 40) and grants '125 total attack "
    "range' (125 + 125) — and every other cached stat matches the game file "
    "leaf for leaf. patch_regression therefore reports a permanent, "
    "patch-independent stat_drift on these two fields (identical flags in "
    "the committed 16.15 report; the 16.16.1 re-pull changed no Kled leaf) "
    "and no value is overridden here. Melee/ranged classification is "
    "unaffected: stats.is_melee reads attackType ('MELEE'), never "
    "attackRange. Residual: base move speed feeds Swiftmarch's "
    "adaptive_force_per_total_move_speed (5%), so a Swiftmarch build "
    "understates adaptive force by 2.0 while the module's modeled abilities "
    "(E Jousting, R Chaaaaaaaarge!!!) are mounted-only — reconciling the "
    "form of the cached stat row is escalated, not patched here.",
]

# HARDCODED: verify on patch updates.  Kled's Grievous Wounds (historically
# on the Bear Trap on a Rope pull) was REMOVED in V25.14 — the e8-interactions
# worklist entry is stale and the wiki cache carries no wound on either Q
# entry (autoresearch pass 11, 2026-08-07).  Empty declaration = no wound.
GRIEVOUS_WOUNDS_SOURCES = frozenset()

MODULE_COVERAGE = coverage(no_damage="P")
