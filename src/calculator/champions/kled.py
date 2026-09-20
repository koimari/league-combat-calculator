"""Kled: full-entry reviewed module.

Option keys consumed by the shared parser: "q_pull", "charge_fraction".
P (Skaarl the Cowardly Lizard): while mounted, damage dealt to the duo is
suffered by Skaarl, whose per-level base health is the mounted pool, the cached
P "Bonus Damage" leveling row.  The dismount and remount cycle is a
revive-boundary pattern and is NOT implemented: the shared grey-health primitive
authors no Skaarl heal, and the pool is documented here as a boundary.
W (Violent Tendencies) is the four-attack empowered burst, its fourth-hit bonus
modeled by the packet.
Q (Pocket Pistol), the dismounted Q, applies Grievous Wounds: the wound rides
the module's Q damage receipts at the patch-wide 40%-for-3s constants that
``healing_reduction`` owns.
"""

from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .contract_vocabulary import coverage
from .engine import SlotCtx, build_parser
from .inputs import bool_option, float_option
from .module_helpers import (
    REVIEWED_MODULE_ASSUMPTIONS,
    ability_slot,
    no_damage,
    ranked_slot,
)
from .shared_mechanics import empowered_auto_entry
from .slot_cc import CC_PER_PART
from .slot_entries import damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named
from .slotlib import simple_damage
from .source_receipts import load_champion_sources

# Bear Trap on a Rope lands twice and the cache times the second hit: the
# trap "collides with the first enemy champion ... forming a tether
# between Kled and the target for 1.75 seconds", and "if it is not broken
# before then, Kled pulls the target 150 units toward him, deals physical
# damage and slows them for 2.5 seconds".  ``time_offset`` runs from the
# cast start, and the cache states no travel time for the trap itself, so
# the throw sits at the cast and the pull 1.75 seconds after it.
_Q_TETHER_SECONDS = data_value(spell_object("Kled", "KledQ"), "TetherPopTime")


@ranked_slot
def _bear_trap(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """Q: the trap's own hit, then the tether's pull hit 1.75s later."""
    # Two cached rows share the name "Physical Damage" — the trap's
    # (30 : 130 + 60% bonus AD) and the pull's (60 : 260 + 120% bonus AD).
    # The first is the one a name lookup reaches, and the cached "Total
    # Physical Damage" row (90 : 390 + 180% bonus AD) is their sum, so the
    # pull reads as the difference without depending on effect order.
    impact = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    pulls = bool(ctx.option("q_pull"))
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


@ability_slot()
def _violent_tendencies(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    rank = ctx.rank_for()
    value = extract_named(
        ability, "Additional Physical Damage", rank, ctx.stats, ctx.target
    )
    return empowered_auto_entry(
        ability,
        rank,
        "physical",
        {
            "name": "Violent Tendencies (first three attacks)",
            "damage_per_hit": 0.0,
            "damage_type": "physical",
        },
        cooldown=0.0,
        empowered_damage=value,
        target_max_health_sensitive=True,
        detail=(
            "Fourth attack of the four-hit Violent Tendencies sequence; 150% "
            "attack speed is state."
        ),
    )


@ranked_slot
def _charge(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> dict[str, Any] | None:
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
    bool_option(
        "q_pull",
        True,
        label="Bear Trap pull resolves",
        rotation={"role": "irrelevant", "slot": "Q"},
    ),
    float_option(
        "charge_fraction",
        1.0,
        minimum=0.0,
        maximum=1.0,
        label="Chaaaaaaaarge distance",
        step=0.25,
        rotation={"role": "self_state", "slot": "R"},
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
# E reviews to no control, and its row still lands as one coarse hit.
# Jousting's row is the Total of the first dash and the recast dash, and
# the cache gives the recast no instant: "Jousting can be recast after 0.5
# seconds of the first dash ending while the target is marked" states when
# the recast becomes *available*, not when it happens, and the dash whose
# ending it counts from has no cached duration.  Half a schedule is not a
# schedule, so the second dash stays folded into the first hit.
MODULE_CC = {"Q": CC_PER_PART, "W": "none", "R": "knockback", "P": "none", "E": "none"}

parse_abilities = build_parser(SLOTS, "Kled", cc_kinds=MODULE_CC)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "Skaarl (P) suffers the mounted duo's damage; his 400 to 1400 by level base "
    "health is the mounted pool.",
    "That pool is the cached P Bonus Damage row in data/champions.json.",
    "The dismount and remount cycle is a revive-boundary pattern and is not modeled; "
    "no Skaarl heal is authored.",
    "The wiki cache carries no Grievous Wounds on either Q entry, so the module "
    "declares no wound source.",
    "Base move speed and attack range are form-attributed: the cache has 305 / 250, "
    "dismounted.",
    "The 16.16 game file Root carries 345 / 125, mounted, and every other cached stat "
    "matches leaf for leaf.",
    "The cached P text reconciles them: dismounting reduces move speed 'by 40 to 305' "
    "and grants '125 total'.",
    "patch_regression therefore reports a permanent stat_drift on those two fields, "
    "and no value is overridden.",
    "stats.is_melee reads attackType MELEE, never attackRange, so the classification "
    "is unaffected.",
    "Base move speed feeds Swiftmarch's adaptive force, so a Swiftmarch build "
    "understates it by 2.0.",
    "The modeled E and R are mounted-only; reconciling the cached row's form is "
    "escalated, not patched here.",
]

# HARDCODED: verify on patch updates.  Kled's Grievous Wounds (the Bear Trap on
# a Rope pull's wound) was REMOVED in V25.14 — the e8-interactions worklist
# entry is stale and the wiki cache carries no wound on either Q
# entry (autoresearch pass 11, 2026-08-07).  Empty declaration = no wound.
GRIEVOUS_WOUNDS_SOURCES = frozenset()

MODULE_COVERAGE = coverage(no_damage="P")
