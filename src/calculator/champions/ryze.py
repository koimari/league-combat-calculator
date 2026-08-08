"""Ryze — CP10.7 full-entry-reviewed packet module."""

from .packet_module import build_packet_module

PACKET_SHA256 = "9da3638ceb40ffff52f60102f737c9576d5d5c13e67a3149499cf273105ff4f2"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Ryze", PACKET_SHA256
)
PACKET_SPEC = SLOTS.packet_spec
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
