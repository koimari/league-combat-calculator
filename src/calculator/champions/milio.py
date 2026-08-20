"""Milio — CP10.4 full-entry-reviewed packet module.

E2 DoT fix: W (Cozy Campfire) heals 25 sourced ticks (Heal per Tick x25 ==
Total Heal) via the heal rule in src/calculator/healing.py.

E8d ally-support: W (Cozy Campfire, Total Heal 70-150 + 15% AP, scope
one_teammate) and R (Breath of Life, Heal 150-350 + 50% AP, scope
self_and_all_teammates) heal allies.  The events are authored by the engine's
ally-support scanner from cached leveling at the cast times; the module
declares W/R in SLOTS so the fight rotation casts them.
"""

from .packet_module import build_packet_module

PACKET_SHA256 = "fce2851d13e50c61a320c2195e1618e540b56a81742d3e44cfaa4a0ffe2c163f"

# Cached kit review: Q "knocks back and stuns the first enemy it hits over
# 1 second" — the enemy the bounced explosion this packet prices then
# damages (and slows).  W, E and R are ally heals/shields and P is an
# enchantment on allies, so no other slot emits an enemy damage event.
MODULE_CC = {"Q": "stun"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Milio",
    PACKET_SHA256,
    # The explosion deals its packet once, at the cast (the fireball's
    # own 0.25-second delay is Milio's cast lockout, not a hit offset) —
    # the boundary claim that carries MODULE_CC into the event ledger.
    single_hit_slots=frozenset({"Q"}),
    cc_kinds=MODULE_CC,
)
MODULE_COVERAGE = {
    slot: ("modeled" if slot == "Q" else "out_of_scope") for slot in "PQWER"
}

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Milio")
