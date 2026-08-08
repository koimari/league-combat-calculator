"""Nami — CP10.5 full-entry-reviewed packet module.

E2 DoT fix: E (Tidecaller's Blessing) prices 3 empowered hits
(this module's packet timing declaration).

E8d ally-support: W (Ebb and Flow) heals the selected teammate.  The event is
authored by the engine's ally-support scanner from the cached W leveling
(Heal 55-155 + 40% AP; scope one_teammate) at the W cast time; the module
declares W in SLOTS so the fight rotation casts it.
"""

from .packet_module import build_packet_module

PACKET_SHA256 = "2590188ce529af2e9f91b00238597c2b85f6f388447f0e0f4f34f6e9c4b692f3"

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
)
PACKET_SPEC = SLOTS.packet_spec
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
