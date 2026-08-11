"""Singed — CP10.7 full-entry-reviewed packet module."""

from .packet_module import build_packet_module
from .engine import build_parser
from .slotlib import with_control

PACKET_SHA256 = "d6e04f1cd92d4f7ddd569c7ba4bb306cdd06c18e230c7ed2a57ef89ba45b3c9c"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Singed", PACKET_SHA256, single_hit_slots=frozenset({"E"})
)
PACKET_SPEC = SLOTS.packet_spec
SLOTS["E"] = with_control(
    SLOTS["E"],
    kind="root",
    duration_attr="Root Duration",
)
parse_abilities = build_parser(SLOTS, "Singed")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
