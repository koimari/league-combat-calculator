"""Generated packet module for Fizz."""

from ..packet_module import build_packet_module

# Packet option keys consumed by packet_module: ["e_variant"]
parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module("Fizz")
REVIEW_STATUS = "reviewed_packet"
