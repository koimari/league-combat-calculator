"""Taric — CP10.8 full-entry-reviewed packet module."""

from .reviewed_batch_08 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Taric")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"E"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
