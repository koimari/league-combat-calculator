"""Lee Sin — full-entry reviewed CP10.3 module."""

from .reviewed_batch_03 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Lee Sin")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E", "R"} else "no_damage") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
