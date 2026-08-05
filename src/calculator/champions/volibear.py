"""Volibear — CP10.9 full-entry-reviewed packet module."""

from .reviewed_batch_09 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Volibear")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"E", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
