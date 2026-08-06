"""Nidalee — CP10.5 full-entry-reviewed packet module.

E2 DoT fix: W Bushwhack (human-form trap) prices 4 sourced 1s ticks
(packet_module _PACKET_TICK_FIXES); the Pounce variant is untouched.
"""

from .reviewed_batch_05 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Nidalee")
# The packet builder consumes these two explicit form selectors at parse time.
VARIANT_OPTION_KEYS = ("q_variant", "w_variant")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
