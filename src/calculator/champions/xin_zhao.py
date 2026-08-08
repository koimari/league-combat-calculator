"""Xin Zhao — CP10.10 full-entry-reviewed packet module."""

from .packet_module import build_packet_module

PACKET_SHA256 = "c39efd0eac006d4b59799a0b3c5de44ef6ec31f9f9a23bea7ab8a25d2f4ccf64"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Xin Zhao", PACKET_SHA256, single_hit_slots=frozenset({"R"})
)
PACKET_SPEC = SLOTS.packet_spec
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
