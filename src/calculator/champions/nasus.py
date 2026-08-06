"""Nasus — CP10.5 full-entry-reviewed packet module.

E2 DoT fix: E (Spirit Fire) prices the initial hit plus 10 sourced 0.5s
zone ticks; R (Fury of the Sands) prices 30 sourced 0.5s ticks
(packet_module _PACKET_TICK_FIXES / _WIKI_ATTRIBUTE_TICK_FIXES).
"""

from .reviewed_batch_05 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Nasus")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
