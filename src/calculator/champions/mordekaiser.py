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

PACKET_SHA256 = "62dd25de0191c8de67cec4f56eaebf7ad2bfa32cf704569b553e18049647d228"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Mordekaiser", PACKET_SHA256
)
PACKET_SPEC = SLOTS.packet_spec
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
REVIEW_STATUS = "reviewed_module"
