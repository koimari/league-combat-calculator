"""Sona — CP10.8 full-entry-reviewed packet module.

E8d ally-support: W (Aria of Perseverance) heals and shields the caster and
one selected teammate.  The event is authored by the engine's ally-support
scanner from the cached W leveling (Heal 30-90 + 30% AP; Shield Strength
25-105 + 25% AP; scope self_and_one_teammate) at the W cast time; the module
declares W in SLOTS so the fight rotation casts it.
"""

from .healing_contract import declare_healing_rule
from .packet_module import build_packet_module

PACKET_SHA256 = "c78392f6b8f667c85594d31be2e6a9c1b7c6504d5cd02e3c5b385271dafc6c06"

# Reviewed crowd control, read from the cached kit.  Q (Hymn of Valor)
# "sends out bolts of sound to the two nearest visible enemies ... Each
# bolt deals magic damage" and applies no control (Power Chord's Tempo
# slow is the passive's empowered attack, not Q).  R (Crescendo) "deals
# magic damage to enemies hit and stuns them for 1.5 seconds".  W and E
# deal no damage, so they carry no reviewable control.
MODULE_CC = {"Q": "none", "R": "stun"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Sona",
    PACKET_SHA256,
    # One bolt on the duel's single target, one chord: each packet is one
    # part and one hit, so the reviewed answer reaches the event ledger.
    single_hit_slots=frozenset({"Q", "R"}),
    cc_kinds=MODULE_CC,
)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "R"} else "out_of_scope") for slot in "PQWER"
}

SELF_HEALING_RULE = declare_healing_rule("Sona")
