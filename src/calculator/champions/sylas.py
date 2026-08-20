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

from dataclasses import replace
from typing import Any

from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module

PACKET_SHA256 = "2c402273f8fc3938c635dbebea26dc7e22901e8a0a07e00ef933ab0d12d77b98"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Sylas",
    PACKET_SHA256,
    # Kingslayer is one strike ("dashes to the front of the target enemy's
    # location then strikes them") and Abduct is one chain hit ("deal magic
    # damage to the first enemy hit"), so each packet is one part and one
    # hit the ledger can time — which is what carries their MODULE_CC
    # answer to the control-armed readers.
    single_hit_slots=frozenset({"W", "E"}),
)
PACKET_SPEC = SLOTS.packet_spec

_packet_chain_lash = SLOTS["Q"]


def _chain_lash(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: the packet's Total Magic Damage row, declared at the cast.

    The row is the lash and the explosion "after a 0.6-second delay"
    summed into one lump, so it is not a single hit the ledger can
    certify.  Declaring the lump's own position — the cast boundary, where
    the lash lands — is the Xin Zhao W shape: it leaves the row's price
    and its aggregation alone and only says when the ledger sees it, which
    is what carries Q's reviewed slow to the control-armed readers.
    """
    entry = _packet_chain_lash(ctx)
    if entry is None:
        return None
    entry["parts"] = tuple(
        replace(part, time_offset=0.0) for part in entry.get("parts") or ()
    )
    return entry


SLOTS["Q"] = _chain_lash

# Reviewed crowd control, read from the cached kit.  W (Kingslayer)
# applies no control.  E (Abduct) deals its damage and "reveal[s] and
# stun[s] them for 0.5 seconds", then "knocks them up for 0.5 seconds upon
# arrival" — two immobilize kinds on the one target, so the reviewed
# answer is the un-narrowed one.  R (Hijack) deals no damage of its own.
#
# Q (Chain Lash) deals "magic damage to enemies hit and slow[s] them for
# 1.5 seconds"; its lumped row is declared at the cast boundary (see
# ``_chain_lash``) rather than split into the two cached rows, which was
# measured to move the row's ledger position.
MODULE_CC = {"W": "none", "E": "immobilize", "Q": "slow"}

parse_abilities = build_parser(SLOTS, "Sylas", cc_kinds=MODULE_CC)

MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Sylas")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "E (Abscond/Abduct) carries no shield in the current kit: the CP-era "
    "SylasEShield atom (80/115/150/185/220 + 100% AP for 2s) was removed "
    "in V10.2 (wiki patch history: 'Abscond Removed: ... No longer "
    "shields ... for 2 seconds upon dashing'); the pinned cached data "
    "has no shield row on either E entry, so the E magic-damage packet "
    "is complete",
]
