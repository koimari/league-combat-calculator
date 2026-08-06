"""Nunu & Willump — CP10.5 full-entry-reviewed packet module.

E2 DoT fix: E (Snowball Barrage) prices the 3-snowball volley from the
per-hit row (packet_module _PACKET_TICK_FIXES overrides the wrong
Snowbound-root row the pinned packet had selected).
"""

from .reviewed_batch_05 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module(
    "Nunu & Willump"
)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
