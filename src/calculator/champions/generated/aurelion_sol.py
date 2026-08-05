"""Generated packet module for Aurelion Sol."""

from ..packet_module import build_packet_module

# Packet option keys consumed by packet_module: ["r_variant"]
parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Aurelion Sol"
)
REVIEW_STATUS = "generated_packet"
