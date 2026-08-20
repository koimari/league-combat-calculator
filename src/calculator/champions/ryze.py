"""Ryze — CP10.7 full-entry-reviewed packet module.

Coverage: P (Arcane Mastery) converts ability power into maximum mana,
which the rest of Ryze's kit then scales off. A resource pool is an axis
the engine does not have, so the slot is out of scope.
"""

from .packet_module import build_packet_module

PACKET_SHA256 = "9da3638ceb40ffff52f60102f737c9576d5d5c13e67a3149499cf273105ff4f2"


# Cached kit review.  Q's runic blast and E's orb only "deal[] magic
# damage".  W "deal[s] magic damage and slow[s] them by 50% for 1.5
# seconds"; its Flux bonus roots instead, but that empowerment has no
# option or damage row of its own here, so the priced cast is the base
# seize and the slow is what it applies.  R's row is the passive "Bonus
# Overload Damage", and the active's root, disarm and silence land on Ryze
# and his own allies as they blink — no enemy control at all.  P only
# raises Ryze's maximum mana.
MODULE_CC = {"Q": "none", "W": "slow", "E": "none", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Ryze",
    PACKET_SHA256,
    # Every Ryze row is one hit: Overload's blast lands on "the first enemy
    # hit", Rune Prison seizes one target, Spell Flux is an orb "upon the
    # target enemy" and R's row is Overload's flux bonus riding that same
    # blast.  Each certifies the cast boundary its reviewed control rides on.
    single_hit_slots=frozenset({"Q", "W", "E", "R"}),
    cc_kinds=MODULE_CC,
)

MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
