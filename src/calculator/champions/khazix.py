"""Kha'Zix — full-entry reviewed CP10.3 module.

Option keys consumed by the shared parser: "p_ready", "q_isolated".
"""

from .reviewed_batch_03 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Kha'Zix")
MODULE_COVERAGE = {
    slot: ("modeled" if slot != "R" else "no_damage") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
