"""Rell — CP10.6 full-entry-reviewed packet module.

E2 DoT fix: R (Magnet Storm) prices 8 sourced 0.25s ticks
(packet_module _PACKET_TICK_FIXES).
"""

from .reviewed_batch_06 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Rell")
VARIANT_OPTION_KEYS = ("w_variant",)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
