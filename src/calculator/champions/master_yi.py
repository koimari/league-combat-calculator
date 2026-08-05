"""Master Yi — CP10.4 full-entry-reviewed packet module."""

from .reviewed_batch_04 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Master Yi")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
