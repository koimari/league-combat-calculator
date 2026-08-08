"""Sona — CP10.8 full-entry-reviewed packet module.

E8d ally-support: W (Aria of Perseverance) heals and shields the caster and
one selected teammate.  The event is authored by the engine's ally-support
scanner from the cached W leveling (Heal 30-90 + 30% AP; Shield Strength
25-105 + 25% AP; scope self_and_one_teammate) at the W cast time; the module
declares W in SLOTS so the fight rotation casts it.
"""

from .packet_module import build_packet_module

PACKET_SHA256 = "c78392f6b8f667c85594d31be2e6a9c1b7c6504d5cd02e3c5b385271dafc6c06"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Sona", PACKET_SHA256
)
PACKET_SPEC = SLOTS.packet_spec
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Sona")
