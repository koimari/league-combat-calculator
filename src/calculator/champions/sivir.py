"""Sivir — CP10.7 full-entry-reviewed packet module."""

from .reviewed_batch_07 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Sivir")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
