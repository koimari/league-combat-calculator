"""Pyke: full-entry-reviewed packet module.

R (Death from Below) carries two per-level rows and they are not the same
number.  The first is the EXECUTE THRESHOLD, 250 to 550 (+ 80% bonus AD)
(+ 1.5 per lethality), below which a champion dies outright; the second is half
of it and is the physical damage everyone above the threshold takes.  This
calculator's target is a full-health champion above it, so R prices the second
row and the threshold is documented rather than priced: an execution is a kill
boundary, not a number.
P (Gift of the Drowned Ones) is three mechanics.  The grey-health store is
priced by the shared primitive, but its consume is a VISION boundary and the
engine has no vision axis, so nothing is paid back.  The stat half is a
CONVERSION declared as ``MODULE_STAT_CONVERSION`` and applied where item stats
fold: his maximum health may not rise except by growth, and the bonus health he
is denied returns as 1 attack damage per 14.
W (Ghostwater Dive) is camouflage plus lethality-scaled movement speed; the
vision half has no axis here and the movement grant is unmodeled.
P and W are ``no_damage``: neither carries an enemy-damage clause, which the
label says and the named missing axes above do not close.
"""

from typing import Any

from ..binary_roots import calculation_coefficient, data_value, spell_object
from ..stat_conversion import BonusHealthConversion
from .contract_vocabulary import coverage
from .engine import SlotCtx
from .module_helpers import ability_slot
from .packet_module import build_packet_module
from .slot_entries import damage_entry
from .slot_extract import (
    ability_name,
    extract_cooldown,
    find_named_leveling,
    sum_modifiers,
)

PACKET_SHA256 = "0c59f6680d5be1482e65394566e4bc1e8e758efcd4d424c85135bf2553a009ea"

# P's stat half, declared where the stat fold reads it.  The cached wiki
# description states one rule twice — "1 bonus attack damage per 14 bonus
# health" and "bonus attack damage equal to 7.143% of bonus health" — and
# 1/14 is the exact form the percent rounds.  P's ``leveling`` is empty, so
# this is a tested constant like Gnar's Mega stats;
# tests/test_pyke.py pins it against the cached sentence.
MODULE_STAT_CONVERSION = BonusHealthConversion(
    source="Gift of the Drowned Ones",
    attack_damage_ratio=1.0 / 14.0,
)


# The binary owns the execute-threshold coefficients and the 50% reduced row;
# the non-execute damage terms are their exact product.
_PYKE_R_SPELL = spell_object("Pyke", "PykeR")
_R_REDUCED_DAMAGE = data_value(_PYKE_R_SPELL, "ReducedDamage")
_R_THRESHOLD_BONUS_AD_RATIO = calculation_coefficient(_PYKE_R_SPELL, "RADDamage")
_R_THRESHOLD_PER_LETHALITY = calculation_coefficient(_PYKE_R_SPELL, "RLethalityDamage")
_R_DAMAGE_BONUS_AD_RATIO = _R_THRESHOLD_BONUS_AD_RATIO * _R_REDUCED_DAMAGE
_R_DAMAGE_PER_LETHALITY = _R_THRESHOLD_PER_LETHALITY * _R_REDUCED_DAMAGE


@ability_slot("R")
def _death_from_below(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    """R: level-based physical damage row + 40% bAD + 0.75 per Lethality."""
    level = ctx.level
    if level < 1:
        return None
    damage_leveling = find_named_leveling(ability, "Per-Level Scaling", occurrence=1)
    if damage_leveling is None:
        return None
    damage = sum_modifiers(damage_leveling, level, ctx.stats, ctx.target)
    damage += _R_DAMAGE_BONUS_AD_RATIO * float(ctx.stat("bonus_attack_damage") or 0.0)
    damage += _R_DAMAGE_PER_LETHALITY * float(ctx.stat("lethality") or 0.0)
    entry = damage_entry(
        ability_name(ability),
        level,
        extract_cooldown(ability, ctx.rank_for()),
        damage,
        "physical",
        # One strike inside the x, at the cast boundary — the claim that
        # carries MODULE_CC's reviewed answer for R into the event ledger.
        event_order_certified="single_hit",
    )
    entry["detail"] = (
        "Non-execute damage (50% of the 250 : 550 + "
        f"{_R_THRESHOLD_BONUS_AD_RATIO:.0%} bonus AD + "
        f"{_R_THRESHOLD_PER_LETHALITY:g} per Lethality execute threshold); "
        "champions below the threshold are executed, not damaged."
    )
    return entry


# Cached kit review.  Q's harpoon deals "physical damage to the first enemy
# hit and pull[s] them ... then slow[s] them by 90% for 1 second": the pull
# is the immobilize the slow rides with.  (Releasing within 0.4 seconds
# thrusts instead, "dealing the same damage" with no displacement; the
# module prices one Bone Skewer row and does not split the two releases,
# so the ability's own recast is what the kind describes.)  E's phantom
# "stun[s] enemies around it" and the champions it hits "also take physical
# damage".  R executes or deals its non-execute damage row and applies no
# control at all.  W (camouflage) and P (grey health) damage nothing.
MODULE_CC = {"Q": "pull", "E": "stun", "R": "none", "P": "none", "W": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Pyke",
    PACKET_SHA256,
    # The harpoon damages the first enemy it hits once and the phantom
    # damages once on its return — the boundary claim that carries
    # MODULE_CC's reviewed answers into the event ledger.
    single_hit_slots=frozenset({"Q", "E"}),
    slot_parsers={
        "R": _death_from_below,
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "P (Gift of the Drowned Ones) stores 9% + 0.2% per Lethality of post-mitigation "
    "damage taken.",
    "With 2 or more visible enemies it is 40% + 0.4% per Lethality, capped at 80 + "
    "800% bonus AD and 55% health.",
    "P's out-of-vision consume heals 100% of the pool, a vision boundary the 1v1 "
    "ledger does not model.",
    "P denies every point of bonus health and returns 1 bonus AD per 14 "
    "(MODULE_STAT_CONVERSION).",
    "The conversion runs in calculate_total_stats on completed bonus health, after "
    "items and runes.",
    "An item passive reading bonus health resolves first, so Riftmaker and Bloodmail "
    "price health he loses.",
    "His displayed bonus health is 0 in game, and those two read it as such.",
    "R (Death from Below) prices the non-execute row: 125 to 275 by level + 40% bonus "
    "AD + 0.75 per Lethality.",
    "That is the 50%-of-threshold amount dealt above the execute threshold "
    "(data/champions.json R Per-Level [1]).",
    "R's execute row, 250 to 550 + 80% bonus AD + 1.5 per Lethality, is a kill "
    "boundary, documented not priced.",
    "P (Gift of the Drowned Ones) deals no enemy damage.",
    "Its store and consume are priced by the shared grey-health primitive, not this "
    "module's SLOTS map.",
    "Pyke is registered in healing.GREY_HEALTH_RULE_CHAMPIONS, so the slot is "
    "no_damage.",
    "W (Ghostwater Dive) carries no enemy-damage formula: a stealth and "
    "decaying-haste self-buff.",
    "The reviewed packet's own no_damage slot declaration names it.",
]
MODULE_COVERAGE = coverage(no_damage="PW")
