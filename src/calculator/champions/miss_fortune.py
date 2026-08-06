"""Miss Fortune — CP10.4 full-entry-reviewed packet module.

E2 DoT fix: E (Make It Rain) prices 8 sourced 0.25s ticks (packet_module
_PACKET_TICK_FIXES).
"""

from .reviewed_batch_04 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module(
    "Miss Fortune"
)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
