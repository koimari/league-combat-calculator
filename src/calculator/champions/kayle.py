"""Kayle — full-entry reviewed CP10.3 module.

Option keys consumed by the shared parser: "p_exalted", "e_empowered".
"""

from .reviewed_batch_03 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Kayle")
MODULE_COVERAGE = {slot: "modeled" for slot in "PQWER"}
REVIEW_STATUS = "reviewed_module"
