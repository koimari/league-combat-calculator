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

Roadmap session (2026-08-21): closes both of Pyke's out_of_scope slots
(P, W).

  - P (Gift of the Drowned Ones): not a damage gap but a stale label.
    P deals no enemy damage (a self-state grey-health passive), and its
    store/consume mechanic is already priced by the shared E8a
    grey-health primitive in ``participant_timeline.py`` — "Pyke" is
    registered in ``healing.GREY_HEALTH_RULE_CHAMPIONS``, and the exact
    sourced constants documented in this module's ASSUMPTIONS below
    (9%/40% store ratio + 0.2%/0.4% per Lethality, 80 + 800% bonus AD
    flat cap, 55% max-health cap) are the same constants the primitive
    reads.  Reclassified from out_of_scope to no_damage on the
    Mordekaiser-W precedent (E8a-priced self-state slots read
    "no_damage": no enemy damage, but the effect is not withheld — it
    is priced elsewhere), with no behavior change.
  - W (Ghostwater Dive): not a damage gap but a stale label — the
    pinned packet already declares W ``kind: "no_damage"``
    (``static/reviewed-packets.json``), so ``build_packet_module`` was
    already emitting a proper zero-damage row while ``MODULE_COVERAGE``
    still read "out_of_scope".  Ghostwater Dive is a stealth/haste
    self-buff with no enemy-damage clause anywhere in the cached entry.
    Reclassified to no_damage on the pinned-packet declaration, with no
    behavior change (the parser output is byte-identical).
"""

from .packet_module import build_packet_module
from .engine import SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, find_named_leveling, sum_modifiers

PACKET_SHA256 = "fa316ebd6555cbf73fb34eabf69516cdc0f150ae01232f50527fd416eb6657db"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Pyke", PACKET_SHA256
)
PACKET_SPEC = SLOTS.packet_spec

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
    damage += _R_DAMAGE_BONUS_AD_RATIO * float(
        ctx.stats.get("bonus_attack_damage", 0.0) or 0.0
    )
    damage += _R_DAMAGE_PER_LETHALITY * float(ctx.stats.get("lethality", 0.0) or 0.0)
    entry = damage_entry(
        ability.get("name", "Death from Below"),
        level,
        extract_cooldown(ability, ctx.rank_for()),
        damage,
        "physical",
    )
    entry["detail"] = (
        "Non-execute damage (50% of the 250 : 550 + "
        f"{_R_THRESHOLD_BONUS_AD_RATIO:.0%} bonus AD + "
        f"{_R_THRESHOLD_PER_LETHALITY:g} per Lethality execute threshold); "
        "champions below the threshold are executed, not damaged."
    )
    return entry


SLOTS = dict(SLOTS)
SLOTS["R"] = _death_from_below
parse_abilities = build_parser(SLOTS, "Pyke")

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
MODULE_COVERAGE = {
    "P": "no_damage",
    "Q": "modeled",
    "W": "no_damage",
    "E": "modeled",
    "R": "modeled",
}
REVIEW_STATUS = "reviewed_module"
