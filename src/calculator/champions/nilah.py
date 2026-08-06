"""Nilah — CP10.5 full-entry-reviewed packet module.

E2 DoT fix: R (Apotheosis) prices 4 sourced 0.25s ticks
(packet_module _PACKET_TICK_FIXES).
"""

from .reviewed_batch_05 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Nilah")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
