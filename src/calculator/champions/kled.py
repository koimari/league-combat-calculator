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

from .reviewed_batch_03 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Kled")
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
]

# HARDCODED: verify on patch updates.  Kled's Grievous Wounds (historically
# on the Bear Trap on a Rope pull) was REMOVED in V25.14 — the e8-interactions
# worklist entry is stale and the wiki cache carries no wound on either Q
# entry (autoresearch pass 11, 2026-08-07).  Empty declaration = no wound.
GRIEVOUS_WOUNDS_SOURCES = frozenset()
GRIEVOUS_WOUNDS_SOURCE_LABELS = {}

MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "no_damage")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
