"""Samira — CP10.7 full-entry-reviewed packet module.

E2 DoT fix: W (Blade Whirl) prices 2 slashes; R (Inferno Trigger) prices
10 sourced 0.2s shots (packet_module _PACKET_TICK_FIXES).
"""

from .reviewed_batch_07 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Samira")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
