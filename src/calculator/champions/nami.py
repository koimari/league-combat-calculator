"""Nami — CP10.5 full-entry-reviewed packet module.

E2 DoT fix: E (Tidecaller's Blessing) prices 3 empowered hits
(this module's packet timing declaration).

E8d ally-support: W (Ebb and Flow) heals the selected teammate.  The event is
authored by the engine's ally-support scanner from the cached W leveling
(Heal 55-155 + 40% AP; scope one_teammate) at the W cast time; the module
declares W in SLOTS so the fight rotation casts it.

Wave-2 ally support (HANDOVER 8.5): the scanner also emits Ebb and Flow's
RETURN BOUNCE as a second heal packet on the same cast ("each bounce
modifying the effectiveness of the next by -20% (+ 15% per 100 AP)" of the
original, never below the sourced Minimum Heal row — the second bounce
keeps 60% + 30% per 100 AP, which is exactly the Minimum Heal row at 0 AP).
Cast on the selected teammate, the stream bounces to the enemy and back to
the same teammate in a two-champion lane (the cached notes allow the final
bounce to re-target an already-affected champion), so the return-bounce
packet uses the same one_teammate scope with its own selection key
(``heal:W:<cast>:bounce``).
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
ASSUMPTIONS = [
    *ASSUMPTIONS,
    "W (Ebb and Flow) emits two ally heal packets per cast on the "
    "selected teammate: the sourced Heal row (55-155 + 40% AP) and the "
    "return bounce at 60% + 30% per 100 AP of the original, never below "
    "the sourced Minimum Heal row (93 + 24% AP at rank 5) — the cached "
    "prose reduces each bounce by -20% (+ 15% per 100 AP) of the "
    "original, and the Minimum row is exactly 60% of the Heal row at "
    "every rank.  The bounce damage against the enemy keeps the module's "
    "full Magic Damage row (the first-bounce reduction of the damage "
    "half is not separately priced).",
]
PACKET_SPEC = SLOTS.packet_spec
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
