"""Generated packet module for Cassiopeia."""

from ..packet_module import build_packet_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Cassiopeia"
)
REVIEW_STATUS = "generated_packet"
