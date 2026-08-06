"""Sylas — CP10.8 full-entry-reviewed packet module, plus the P1 E-shield note.

The CP-era "SylasEShield" atom (Abscond/Abduct shield, 80/115/150/185/220
+ 100% AP for 2s) is HISTORICAL: the wiki patch history records it as
removed — "Abscond Removed: ... No longer shields for 80 / 115 / 150 /
185 / 220 (+ 100% AP) against magic damage for 2 seconds upon dashing"
(V10.2 patch note).  The pinned cached data (patch 16.15) carries no
shield row on either E entry, matching the live kit, so the module's E
packet (Abduct magic damage) is complete — the shield atom is documented
as a stale receipt, not a missing mechanic.

E1-b2: Sylas is in HEALING_RULE_CHAMPIONS — W Kingslayer's
missing-health-scaled heal (Minimum/Maximum Heal rows) is authored by
``derive_self_healing`` (test_sylas_kingslayer_heals_scaled_by_missing).
"""

from .reviewed_batch_08 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Sylas")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "E (Abscond/Abduct) carries no shield in the current kit: the CP-era "
    "SylasEShield atom (80/115/150/185/220 + 100% AP for 2s) was removed "
    "in V10.2 (wiki patch history: 'Abscond Removed: ... No longer "
    "shields ... for 2 seconds upon dashing'); the pinned cached data "
    "has no shield row on either E entry, so the E magic-damage packet "
    "is complete",
]
