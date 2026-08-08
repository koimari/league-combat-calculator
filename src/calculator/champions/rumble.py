"""Rumble — CP10.6 packet module with the E9-1 R gap fix.

E9-1 closes the remaining audit gap: R (The Equalizer) priced ONE tick
of the Burning DoT.  The wiki cache carries "Magic Damage per Tick"
(30/50/70 + 8.75% AP) and "Maximum Magic Damage" (600/1000/1400 +
175% AP): 20 ticks at 0.25 seconds over up to 5 seconds of Burning
("Enemies may be Burning for up to 5 seconds, for a total of 20
instances of its effect"). This module's packet timing declaration
prices all 20 ticks.

The heat/Danger Zone system remains documented out_of_scope (P/W
no_damage rows); rotation numbers assume no heat state (the CP-era
review boundary).  Q/E damage packets are correct.
"""

from .packet_module import build_packet_module

PACKET_SHA256 = "c18c1e6e7005c17066acf180ec68a2013bb656c20a88655a536f0a2bc9a078f5"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Rumble",
    PACKET_SHA256,
    packet_tick_fixes={
        "The Equalizer": {
            "count": 20,
            "first_tick": 0.25,
            "tick_interval": 0.25,
            "dot_duration": 5.0,
        }
    },
)
PACKET_SPEC = SLOTS.packet_spec
ASSUMPTIONS = list(ASSUMPTIONS) + [
    "R (The Equalizer) prices all 20 Burning ticks (Magic Damage per "
    "Tick x20 == Maximum Magic Damage 600/1000/1400 + 175% AP) at "
    "0.25-second intervals over up to 5 seconds (packet_module "
    "local packet timing declaration). The initial rocket impact has no separate "
    "damage row in the cache.",
    "The heat/Danger Zone system is state outside the damage model: "
    "Q/E/R rotation numbers assume no heat state (the CP-era review "
    "boundary).",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
