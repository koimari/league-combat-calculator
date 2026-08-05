"""Generated packet module for Kled."""

from ..packet_module import build_packet_module

# Packet option keys consumed by packet_module: ["q_variant"]
parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module("Kled")
REVIEW_STATUS = "generated_packet"
