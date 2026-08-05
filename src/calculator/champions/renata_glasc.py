"""Renata Glasc — CP10.6 full-entry-reviewed packet module."""

from .reviewed_batch_06 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module(
    "Renata Glasc"
)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
