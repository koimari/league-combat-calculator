"""Zac — CP10.10 full-entry-reviewed packet module.

E3 boundary: the worklist assigns Zac no damage-relevant stack mechanic.
The passive's Goo chunks heal Zac (4% : 8.47% max health per chunk) and
reduce W's cooldown; the resurrection is a death passive. Neither
changes outgoing damage, so no stack slot is added — the chunk heal row
the packet prices as target-max-health damage is the passive's existing
packet read and is left untouched (not part of the E3 worklist).

E4 boundary: the E4-3 worklist skips Zac — R (Let's Bounce!) is the
self-movement rework, not a summoned unit (the "Champion summoned
units" page lists only Zac's Cell Division Bloblets, which are a death
passive with no outgoing damage).  No summon slot is added; the
reviewed bounce packet pricing is unchanged.
"""

from .reviewed_batch_10 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Zac")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
