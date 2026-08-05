"""Udyr — CP10.9 full-entry-reviewed packet module."""

from .reviewed_batch_09 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Udyr")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
