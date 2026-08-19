"""Xin Zhao — CP10.10 full-entry-reviewed packet module."""

from .packet_module import build_packet_module

PACKET_SHA256 = "c39efd0eac006d4b59799a0b3c5de44ef6ec31f9f9a23bea7ab8a25d2f4ccf64"

# Wind Becomes Lightning ends in a thrust "dealing physical damage to
# enemies hit ... and slowing them by 50%" — the cast slows the target it
# damages, even though this packet prices only the "Physical Damage per
# Slash" leg.  Audacious Charge "slow[s] all targets hit by 30% for 0.5
# seconds".  Crescent Guard's knockback and stun reach only "targets hit
# that are not Challenged", and its own passive marks the duel target —
# "Xin Zhao's basic attacks and Audacious Charge apply the Challenged mark
# to enemy champions hit" — so the one enemy this module prices is never
# displaced by it.
#
# Q stays UNREVIEWED, so this kit keeps the coarse control-armed scan.  Its
# packet reads "Bonus Physical Damage", one of the three empowered attacks,
# and only "the third attack knocks up the target" — no slot-wide answer
# covers a row that is one unnamed attack of three (the Annie Pyromania
# rule).
MODULE_CC = {"W": "slow", "E": "slow", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Xin Zhao",
    PACKET_SHA256,
    # W's slash, E's arrival and R's sweep are one hit each at the cast.
    single_hit_slots=frozenset({"W", "E", "R"}),
    cc_kinds=MODULE_CC,
)
PACKET_SPEC = SLOTS.packet_spec
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Xin Zhao")
