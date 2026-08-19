"""Singed — CP10.7 full-entry-reviewed packet module."""

from .packet_module import build_packet_module

PACKET_SHA256 = "d6e04f1cd92d4f7ddd569c7ba4bb306cdd06c18e230c7ed2a57ef89ba45b3c9c"

# Reviewed crowd control, read from the cached kit.  Q (Poison Trail)
# "inflicts poison to enemies within" and applies no control — the
# grounding slow belongs to W (Mega Adhesive), which deals no damage.  E
# (Fling) "flings the target enemy 550 units over himself over 0.693
# seconds, dealing magic damage" and its second clause calls that throw
# "the displacement"; the cached text names no narrower airborne kind, and
# the root it can follow with is conditional on landing in W's field.
MODULE_CC = {"Q": "none", "E": "airborne"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Singed",
    PACKET_SHA256,
    # The packet prices one poison tick per cast (base 5-15 at a 1s
    # cooldown), so the Q row is one part and one hit, same as E's fling.
    single_hit_slots=frozenset({"Q", "E"}),
    cc_kinds=MODULE_CC,
)
PACKET_SPEC = SLOTS.packet_spec
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
