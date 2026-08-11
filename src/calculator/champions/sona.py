"""Sona — CP10.8 full-entry-reviewed packet module.

E8d ally-support: W (Aria of Perseverance) heals and shields the caster and
one selected teammate.  The event is authored by the engine's ally-support
scanner from the cached W leveling (Heal 30-90 + 30% AP; Shield Strength
25-105 + 25% AP; scope self_and_one_teammate) at the W cast time; the module
declares W in SLOTS so the fight rotation casts it.

Wave-2 ally support (HANDOVER 8.5): the W heal is authored once by the E1
rule in healing.py (self copy + fan-out clone to the selected teammate
under the heal:W:<cast> selection key, "heals herself and sends out a tone
to heal the most wounded allied champion nearby") and the Melody shield is
scanner-owned under shield:W:<cast>; both packets expose independent
roster selection keys.  The deterministic roster model treats the selected
teammate as the "most wounded" target.
"""

from .packet_module import build_packet_module

PACKET_SHA256 = "c78392f6b8f667c85594d31be2e6a9c1b7c6504d5cd02e3c5b385271dafc6c06"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Sona", PACKET_SHA256
)
ASSUMPTIONS = [
    *ASSUMPTIONS,
    "W (Aria of Perseverance) heals the caster and the selected teammate "
    "the sourced Heal (30-90 + 30% AP) via the E1-rule fan-out "
    "(heal:W:<cast> key) and shields the caster and the same selected "
    "teammate the sourced Melody Shield Strength (25-105 + 25% AP) for "
    "1.5s (shield:W:<cast> key); the in-game 'most wounded allied "
    "champion nearby' selection is the explicit roster teammate choice.",
]
PACKET_SPEC = SLOTS.packet_spec
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
