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
    "Q Grievous Wounds: the dismounted Pocket Pistol applies Grievous "
    "Wounds (e8-interactions worklist; the wound strength/duration are "
    "the engine's 40%-for-3s constants).  The module's Q slot prices the "
    "mounted Bear Trap on a Rope, so the Pocket Pistol wound rides the "
    "same Q damage receipts — a dismounted Q hit wounds the target for "
    "the patch-wide window, refreshed per hit.",
]

# HARDCODED: verify on patch updates — the e8-interactions worklist
# (data/worklists/e8-interactions.json) pins Kled's Q (Pocket Pistol) as
# a Grievous Wounds source; the strength/duration are the engine
# constants (GRIEVOUS_WOUNDS_FACTOR/DURATION), not module numbers.
GRIEVOUS_WOUNDS_SOURCES = frozenset({"Q"})
# The slot's first cached entry is the mounted Bear Trap; the wounding
# ability is the dismounted Pocket Pistol (Q[1]).
GRIEVOUS_WOUNDS_SOURCE_LABELS = {"Q": "Pocket Pistol"}

MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "no_damage")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
