"""Generated packet module for Briar."""

from ..packet_module import build_packet_module

# Packet option keys consumed by packet_module: ["w_variant"]
parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module("Briar")
REVIEW_STATUS = "generated_packet"
