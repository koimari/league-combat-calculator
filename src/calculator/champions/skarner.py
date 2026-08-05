"""Skarner — CP10.7 full-entry-reviewed packet module."""

from .reviewed_batch_07 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Skarner")
VARIANT_OPTION_KEYS = ("q_variant",)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
