"""Nami — CP10.5 full-entry-reviewed packet module.

E2 DoT fix: E (Tidecaller's Blessing) prices 3 empowered hits
(packet_module _PACKET_TICK_FIXES).
"""

from .reviewed_batch_05 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Nami")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
