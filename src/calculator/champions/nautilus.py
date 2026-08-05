"""Nautilus — CP10.5 full-entry-reviewed packet module."""

from .reviewed_batch_05 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Nautilus")
MODULE_COVERAGE = {slot: "modeled" for slot in "PQWER"}
REVIEW_STATUS = "reviewed_module"
