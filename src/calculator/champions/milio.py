"""Milio — CP10.4 full-entry-reviewed packet module.

E2 DoT fix: W (Cozy Campfire) heals 25 sourced ticks (Heal per Tick x25 ==
Total Heal) via the heal rule in src/calculator/healing.py.
"""

from .reviewed_batch_04 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Milio")
MODULE_COVERAGE = {
    slot: ("modeled" if slot == "Q" else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
