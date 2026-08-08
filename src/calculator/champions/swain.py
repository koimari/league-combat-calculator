"""Swain — CP10.8 full-entry-reviewed packet module."""

from .packet_module import build_packet_module

PACKET_SHA256 = "65d9e8cd0840ba7f346dd7faad26a485494c4825f438be91e63491b17ecc5169"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Swain", PACKET_SHA256
)
PACKET_SPEC = SLOTS.packet_spec
VARIANT_OPTION_KEYS = ("r_variant",)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Swain")
