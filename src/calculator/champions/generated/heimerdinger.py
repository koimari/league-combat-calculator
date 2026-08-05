"""Generated packet module for Heimerdinger."""

from ..packet_module import build_packet_module

# Packet option keys consumed by packet_module: ["e_variant", "w_variant"]
parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Heimerdinger"
)
REVIEW_STATUS = "generated_packet"
