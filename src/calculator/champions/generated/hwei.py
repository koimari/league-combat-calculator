"""Generated packet module for Hwei."""

from ..packet_module import build_packet_module

# Packet option keys consumed by packet_module: ["e_variant", "q_variant"]
parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module('Hwei')
REVIEW_STATUS = 'reviewed_packet'
