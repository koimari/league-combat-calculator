"""Taric — CP10.8 full-entry-reviewed packet module.

E8d ally-support: Q (Starlight's Touch) heals himself and nearby allies per
stocked charge (cached prose: "25 (+ 15% AP) (+ 1% of his maximum health) per
charge"; the cached Q leveling exposes only "Maximum Charges", not a heal
row).  The engine's ally-support scanner cannot author the heal from the
cached leveling, so the Q heal is NOT emitted as a support packet — see E8d
reply for the missing hook.  R (Cosmic Radiance) is invulnerability state
(2.5s), documented as such, not a heal/shield.
"""

from .engine import build_parser
from .packet_module import build_packet_module
from .slotlib import with_control

PACKET_SHA256 = "c4661e1dfa5a63e1d512d64efc3bbb6cfb5e5d22f3c5d3e08c363f4d5c672cb4"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Taric", PACKET_SHA256
)
SLOTS["E"] = with_control(
    SLOTS["E"],
    kind="stun",
    duration_attr="Stun Duration",
)
parse_abilities = build_parser(SLOTS, "Taric")
PACKET_SPEC = SLOTS.packet_spec
ASSUMPTIONS.append("E's sourced 1.5-second stun counts as target action downtime")
ASSUMPTIONS.extend(
    [
        "W (Bastion) shields Taric and the linked selected teammate the "
        "sourced Shield Strength as a live % of the PROTECTED TARGET's "
        "maximum health (scanner packet with a max-health amount formula "
        "and 2.5s duration, selection key shield:W:<cast>).",
        "Q (Starlight's Touch) heals Taric and every selected teammate "
        "the sourced per-charge heal (25 + 15% AP + 1% of his maximum "
        "health per charge, capped at the 5-charge maximum) via the E1 "
        "rule and its self_and_all_teammates fan-out; the scanner defers "
        "the slot (no heal row in the cached Q leveling).",
        "R (Cosmic Radiance) grants the caster and every selected "
        "teammate invulnerability after the sourced 2.5s descent for the "
        "sourced 2.5s window (state packet).",
    ]
)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"E"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
