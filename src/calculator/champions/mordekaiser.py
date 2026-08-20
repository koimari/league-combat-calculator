"""Mordekaiser — CP10.4 full-entry-reviewed packet module.

E8a: the W (Indestructible) grey-health receipts live in the shared
participant-timeline primitive, which stores 45% of post-mitigation
damage dealt + 7.5% of pre-mitigation damage taken as Potential Shield
(capped at 30% of maximum health) and pays the recast heal
("Shield to Healing" 35/37.5/40/42.5/45% by W rank) at the earliest
recast time (W cast + 0.5 s per the wiki).  The module keeps pricing W
as a non-damaging state-only slot; the engine's cast timeline still
schedules the W cast that arms the recast.
"""

from .packet_module import build_packet_module
from .slotlib import simple_damage

PACKET_SHA256 = "62dd25de0191c8de67cec4f56eaebf7ad2bfa32cf704569b553e18049647d228"

# Death's Grasp lands on its own delay: Mordekaiser "summons a claw in the
# target direction that grants sight of the area. After 0.5 seconds, it
# deals magic damage to enemies within and pulls them over 250 units"
# (data/champions.json Mordekaiser E).  The cached entry attaches no
# cast-time qualifier to the number, so it is read from the cast start as
# written.
_E_CLAW_SECONDS = 0.5


# Reviewed crowd control, read from the cached kit.  Obliterate "deal[s]
# magic damage to enemies within, increased if only one enemy is hit" and
# applies nothing else.  Death's Grasp "deals magic damage to enemies
# within and pulls them over 250 units" — the pull lands with the damage
# on the same 0.5-second claw, which the slot now authors.  P (Darkness
# Rise) is a basic-attack/aura row, and W and R author no damage part.
MODULE_CC = {"Q": "none", "E": "pull"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Mordekaiser",
    PACKET_SHA256,
    packet_part_timings={"E": {"time_offset": _E_CLAW_SECONDS}},
    slot_parsers={
        # The reviewed packet folded Obliterate's per-level term into its per-rank
        # base, so one index served both and the level term was read at the rank —
        # at level 18 rank 5 the swing priced its level-5 scaling.  Reading the
        # cached row through the shared slot repairs the axis without changing
        # which row is read.
        "Q": simple_damage(
            attr="Magic Damage",
            dmg_type="magic",
            event_order_certified="single_hit",
        ),
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Indestructible) stores 45% of post-mitigation damage dealt and "
    "7.5% of pre-mitigation damage taken as Potential Shield (capped at "
    "30% of maximum health); the recast (modeled at W cast + 0.5 s, the "
    "wiki's earliest available recast) heals the Shield-to-Healing % "
    "(35/37.5/40/42.5/45% by W rank) of the stored shield — the E8a "
    "grey-health primitive authors it from the incoming/outgoing "
    "ledgers. Shield conversion and both decay curves are state.",
]

MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "E"} else "out_of_scope") for slot in "PQWER"
}
