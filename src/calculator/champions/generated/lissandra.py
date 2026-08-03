"""Generated packet module for Lissandra."""

from ..packet_module import build_packet_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module("Lissandra")
REVIEW_STATUS = "reviewed_packet"
