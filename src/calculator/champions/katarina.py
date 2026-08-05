"""Katarina — full-entry reviewed CP10.3 module.

Option keys consumed by the shared parser: "p_daggers", "r_daggers".
"""

from .reviewed_batch_03 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Katarina")
MODULE_COVERAGE = {
    slot: ("modeled" if slot != "W" else "no_damage") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
