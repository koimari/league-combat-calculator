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
"""

from .packet_module import build_packet_module
from .engine import SlotCtx
from .slotlib import damage_entry, extract_cooldown, find_named_leveling, sum_modifiers

PACKET_SHA256 = "fa316ebd6555cbf73fb34eabf69516cdc0f150ae01232f50527fd416eb6657db"


# The non-execute damage row's scaling, from the wiki prose on R:
# 50% of the threshold amount -> 40% bonus AD and 0.75 per 1 Lethality.
_R_DAMAGE_BONUS_AD_RATIO = 0.40
_R_DAMAGE_PER_LETHALITY = 0.75
# The execute threshold itself (documented, not priced): 80% bonus AD
# and 1.5 per 1 Lethality on the 250 : 550 per-level row.
_R_THRESHOLD_BONUS_AD_RATIO = 0.80
_R_THRESHOLD_PER_LETHALITY = 1.5


def _death_from_below(ctx: SlotCtx):
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
        ability.get("name", "Death from Below"),
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

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Gift of the Drowned Ones) stores 9% (+ 0.2% per 1 Lethality) of "
    "post-mitigation damage taken as grey health (40% + 0.4% per "
    "Lethality with 2+ visible enemies), capped at 80 + 800% bonus AD "
    "and 55% of maximum health; the out-of-vision consume heals 100% of "
    "the stored pool and is a vision boundary the 1v1 ledger does not "
    "model (the E8a grey-health primitive authors the store receipts, "
    "no in-window heal)",
    "R (Death from Below) prices the wiki's non-execute damage row — "
    "125 : 275 (based on level) (+ 40% bonus AD) (+ 0.75 per 1 "
    "Lethality) physical damage, the 50%-of-threshold amount dealt to "
    "enemies above the execute threshold (data/champions.json R "
    "'Per-Level Scaling' [1]). The execute threshold row (250 : 550 + "
    "80% bonus AD + 1.5 per Lethality) is a kill boundary and is "
    "documented, not priced as damage.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E", "R"} else "out_of_scope") for slot in "PQWER"
}
