"""Generated packet module for Swain."""

from ..packet_module import build_packet_module

# Packet option keys consumed by packet_module: ["r_variant"]
parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module('Swain')
REVIEW_STATUS = 'reviewed_packet'
