"""Generated packet module for Karma."""

from ..packet_module import build_packet_module

# Packet option keys consumed by packet_module: ["q_variant"]
parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module("Karma")
REVIEW_STATUS = "reviewed_packet"
