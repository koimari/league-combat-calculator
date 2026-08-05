"""Kindred — full-entry reviewed CP10.3 module.

Option keys consumed by the shared parser: "marks", "w_attacks", "e_stacks".
"""

from .reviewed_batch_03 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Kindred")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E"} else "no_damage") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
