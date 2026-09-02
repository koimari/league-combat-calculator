"""Pyke — CP10.6 full-entry-reviewed packet module.

E5-2 fix — Death from Below (R): the reviewed packet pinned the
1.5x-threshold array (375-825 == 1.5 x the 250-550 execute threshold)
to the first three R ranks as flat MAGIC damage and dropped every
scaling term.  The wiki (data/champions.json R) carries two per-level
rows:

- "Per-Level Scaling" [0]: 250 : 550 (+ 80% bonus AD) (+ 1.5 per 1
  Lethality) — the EXECUTE THRESHOLD: champions below it die outright.
- "Per-Level Scaling" [1]: 125 : 275 (+ 40% bonus AD) (+ 0.75 per 1
  Lethality) — the physical damage dealt to non-executed enemies
  ("Other enemies hit and enemy champions above the threshold are
  instead dealt 50% of the amount as physical damage").

The calculator's target is a full-health champion above the threshold,
so R prices the sourced damage row (level-based, physical) plus the
bAD and lethality terms.  The threshold itself is documented, not
priced as damage — an execution is a kill boundary, not a number.

P and W are ``no_damage``: neither carries an enemy-damage clause, and
the pinned packet declares both so.  Each still has a named missing
axis, which the label does not close:

- P (Gift of the Drowned Ones) is three mechanics. The grey-health store
  is priced by the shared E8a primitive (probe: ``grey_health_stored``
  80.0 at level 18 with no items — the flat cap; "Pyke" is registered in
  ``healing.GREY_HEALTH_RULE_CHAMPIONS``), but its consume is a VISION
  boundary ("while Pyke is not visible to enemies") and the engine has no
  vision axis, so nothing is paid back. The stat half is a CONVERSION,
  declared as ``MODULE_STAT_CONVERSION`` and applied where item stats are
  folded: his maximum health may not rise except by growth, and the bonus
  health he is denied returns as 1 attack damage per 14. Probe at level
  18 with Warmog's Armor: health 2540, attack damage 96 -> 176 (the
  wiki's own conversion table reads 71.4 for Warmog's 1000-health stat
  block, and Vitality raises that block to 1120 before the conversion).
- W (Ghostwater Dive) is camouflage plus lethality-scaled movement speed:
  no vision/stealth axis, and ``stat_buff`` has no movement-speed key.
"""

from typing import Any

from ..binary_roots import calculation_coefficient, data_value, spell_object
from ..stat_conversion import BonusHealthConversion
from .engine import SlotCtx
from .module_contract import coverage
from .packet_module import build_packet_module
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    find_named_leveling,
    sum_modifiers,
)

PACKET_SHA256 = "fa316ebd6555cbf73fb34eabf69516cdc0f150ae01232f50527fd416eb6657db"

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


def _death_from_below(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: level-based physical damage row + 40% bAD + 0.75 per Lethality."""
    ability = ctx.ability("R", 0)
    if ability is None:
        return None
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
MODULE_CC = {"Q": "pull", "E": "stun", "R": "none"}

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
    "P (Gift of the Drowned Ones) stores 9% (+ 0.2% per 1 Lethality) of "
    "post-mitigation damage taken as grey health (40% + 0.4% per "
    "Lethality with 2+ visible enemies), capped at 80 + 800% bonus AD "
    "and 55% of maximum health; the out-of-vision consume heals 100% of "
    "the stored pool and is a vision boundary the 1v1 ledger does not "
    "model (the E8a grey-health primitive authors the store receipts, "
    "no in-window heal)",
    "P (Gift of the Drowned Ones) denies every point of bonus health and "
    "returns it as 1 bonus attack damage per 14 "
    "(MODULE_STAT_CONVERSION, applied in stats.calculate_total_stats on "
    "the completed bonus health, after item multipliers and rune grants "
    "as the wiki's own note orders it). Residual: an item passive that "
    "reads bonus health resolves before that denial, so Riftmaker's Void "
    "Infusion and Overlord's Bloodmail still price the health he never "
    "keeps; his displayed bonus health is 0 in game and those two would "
    "read it as such.",
    "R (Death from Below) prices the wiki's non-execute damage row — "
    "125 : 275 (based on level) (+ 40% bonus AD) (+ 0.75 per 1 "
    "Lethality) physical damage, the 50%-of-threshold amount dealt to "
    "enemies above the execute threshold (data/champions.json R "
    "'Per-Level Scaling' [1]). The execute threshold row (250 : 550 + "
    "80% bonus AD + 1.5 per Lethality) is a kill boundary and is "
    "documented, not priced as damage.",
    "P (Gift of the Drowned Ones) deals no enemy damage; its "
    "store/consume mechanic is priced by the shared E8a grey-health "
    "primitive (participant_timeline.py), not this module's own SLOTS "
    "map -- Pyke is registered in healing.GREY_HEALTH_RULE_CHAMPIONS. "
    "Reclassified from out_of_scope to no_damage (a stale label, not a "
    "computation change): the passive was already priced, just not "
    "through this module's own slot declaration.",
    "W (Ghostwater Dive) carries no enemy-damage formula of any kind "
    "(the reviewed packet's own no_damage slot declaration already "
    "names it): a stealth/decaying-haste self-buff. Reclassified from "
    "out_of_scope to no_damage (a stale label, not a computation "
    "change): the slot was previously mislabeled out_of_scope despite "
    "the packet layer already carrying no enemy-damage formula for it.",
]
MODULE_COVERAGE = coverage(no_damage="PW")
