"""Taric — CP10.8 full-entry-reviewed packet module.

E8d ally-support: Q (Starlight's Touch) heals himself and nearby allies per
stocked charge (cached prose: "25 (+ 15% AP) (+ 1% of his maximum health) per
charge"; the cached Q leveling exposes only "Maximum Charges", not a heal
row).  The engine's ally-support scanner cannot author the heal from the
cached leveling, so the Q heal is NOT emitted as a support packet — see E8d
reply for the missing hook.  R (Cosmic Radiance) is invulnerability state
(2.5s), documented as such, not a heal/shield.
"""

from .packet_module import build_packet_module
from .slotlib import simple_damage

PACKET_SHA256 = "c4661e1dfa5a63e1d512d64efc3bbb6cfb5e5d22f3c5d3e08c363f4d5c672cb4"

# Reviewed crowd control, read from the cached kit: E (Dazzle) "projects a
# beam of starlight in the target direction that deals magic damage to
# enemies hit and stuns them for 1.5 seconds".  Q, W and R deal no damage
# — heal, shield and invulnerability — and P is an attack-stream rider, so
# E is the whole of this kit's reviewable control.
MODULE_CC = {"E": "stun"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Taric",
    PACKET_SHA256,
    slot_parsers={
        # One beam, one blow, so the row is a hit the ledger can time.
        "E": simple_damage(
            attr="Magic Damage",
            dmg_type="magic",
            ranks="rank",
            source=("E", 0),
            event_order_certified="single_hit",
        )
    },
    cc_kinds=MODULE_CC,
)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"E"} else "out_of_scope") for slot in "PQWER"
}

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Taric")
