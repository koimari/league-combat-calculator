"""LeBlanc — full-entry reviewed CP10.3 module.

Option keys consumed by the shared parser: "q_consume", "e_chain_complete", "r_mimic".
"""

from .reviewed_batch_03 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("LeBlanc")
MODULE_COVERAGE = {
    slot: ("modeled" if slot != "P" else "no_damage") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
