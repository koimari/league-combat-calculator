"""Nami — CP10.5 full-entry-reviewed packet module.

E2 DoT fix: E (Tidecaller's Blessing) prices 3 empowered hits
(packet_module _PACKET_TICK_FIXES).

E8d ally-support: W (Ebb and Flow) heals the selected teammate.  The event is
authored by the engine's ally-support scanner from the cached W leveling
(Heal 55-155 + 40% AP; scope one_teammate) at the W cast time; the module
declares W in SLOTS so the fight rotation casts it.
"""

from .reviewed_batch_05 import build_batch_module

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Nami")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
