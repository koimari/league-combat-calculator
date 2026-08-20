"""Nami — CP10.5 full-entry-reviewed packet module.

E2 DoT fix: E (Tidecaller's Blessing) prices 3 empowered hits
(this module's packet timing declaration).

E8d ally-support: W (Ebb and Flow) heals the selected teammate.  The event is
authored by the engine's ally-support scanner from the cached W leveling
(Heal 55-155 + 40% AP; scope one_teammate) at the W cast time; the module
declares W in SLOTS so the fight rotation casts it.
"""

from .healing_contract import declare_healing_rule
from .packet_module import build_packet_module

PACKET_SHA256 = "2590188ce529af2e9f91b00238597c2b85f6f388447f0e0f4f34f6e9c4b692f3"

# Cached kit review.  Q's bubble deals magic damage "and suspend[s] them for
# 1.5 seconds" — a suspension, the Wiki's airborne class, and the kind is not
# narrowed further because the cached text never says knock up or back.  W
# "deals magic damage to enemies" and applies nothing.  E empowers three
# attacks/abilities that "each deal bonus magic damage and slow enemies for 1
# second".  R deals magic damage while "knocking them up for 0.5 seconds, and
# slowing them by 70%" — the knock-up is the immobilize the slow rides with.
# P is absent: Surging Tides only grants allies movement speed and damages
# nothing, so no event of its own could carry an answer.
MODULE_CC = {"Q": "airborne", "W": "none", "E": "slow", "R": "knockup"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Nami",
    PACKET_SHA256,
    packet_tick_fixes={
        "Tidecaller's Blessing": {
            "count": 3,
            "first_tick": 0.5,
            "tick_interval": 1.0,
        }
    },
    # Aqua Prison's bubble, Ebb and Flow's stream and Tidal Wave's crest each
    # deal their packet once, at the cast — the boundary claim that carries
    # MODULE_CC's reviewed answers into the event ledger.  E already authors
    # its own three-tick timing above.
    single_hit_slots=frozenset({"Q", "W", "R"}),
    cc_kinds=MODULE_CC,
)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}

SELF_HEALING_RULE = declare_healing_rule("Nami")
