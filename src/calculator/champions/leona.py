"""Leona — full-entry reviewed CP10.3 module.

E8c addition over the reviewed module:
- W (Eclipse) is defense, not a shield: cached leveling rows carry a
  per-instance "Flat Damage Reduction" (8/12/16/20/24, prose-capped at
  50% of the damage instance) plus bonus armor and bonus magic
  resistance (20/27.5/35/42.5/50 + 20% of bonus, 3s, extended 3s when
  the detonation hits).  The shared ledger's shield events price
  absorbing barriers, and its stat-buff events carry no armor/MR axis,
  so Eclipse is documented as mitigation state with the sourced
  constants pinned here — no flat shield amount is invented.  The W
  detonation damage keeps its reviewed packet read.

Option key consumed by the shared parser: "p_marks".
"""

from .reviewed_batch_03 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Leona")

# HARDCODED: verify on patch updates — Eclipse's defense rows are cached
# leveling data (data/champions.json, Leona W): Flat Damage Reduction
# 8/12/16/20/24 (prose: "up to 50% of the damage instance"), Bonus
# Armor and Bonus Magic Resistance 20/27.5/35/42.5/50 + 20% of bonus,
# duration 3s extended 3s on hit (prose).  The ledger's shield events
# cannot price per-instance pre-mitigation reduction or resistance
# buffs, so these stay documented constants.
_ECLIPSE_FLAT_REDUCTION_RANKED = (8.0, 12.0, 16.0, 20.0, 24.0)
_ECLIPSE_REDUCTION_CAP = 0.50  # capped at 50% of the damage instance
_ECLIPSE_BONUS_RESIST_RANKED = (20.0, 27.5, 35.0, 42.5, 50.0)
_ECLIPSE_BONUS_RESIST_RATIO = 0.20  # +20% of bonus resist
_ECLIPSE_DURATION_SECONDS = 3.0
_ECLIPSE_EXTENSION_SECONDS = 3.0

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Eclipse) is documented as mitigation state, not a shield: "
    "per-instance flat damage reduction 8/12/16/20/24 (capped at 50% of "
    "the instance) plus bonus armor/MR 20/27.5/35/42.5/50 + 20% of "
    "bonus for 3s (extended 3s on detonation hit) — cached leveling "
    "constants; the ledger's shield events cannot express pre-mitigation "
    "reduction or resistance buffs, so no flat shield amount is invented",
]

MODULE_COVERAGE = {slot: "modeled" for slot in "PQWER"}
REVIEW_STATUS = "reviewed_module"
