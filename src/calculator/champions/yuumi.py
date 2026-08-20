"""Yuumi — CP10.10 full-entry-reviewed packet module.

E8d ally-support: E (Zoomies) grants the caster a shield (Shield 65-165 +
40% AP; scope self per the cached "grants herself a shield" prose).  R
(Final Chapter) heals allies hit by the waves (Heal per Hit x5 == Total
Heal, scope one_teammate).  Both events are authored by the engine's
ally-support scanner from cached leveling at the cast times; the module
declares E/R in SLOTS so the fight rotation casts them.  The attached-bonus
anchor transfer of E ("Affects the Anchor instead of Yuumi") is a scope
detection the scanner does not express — see E8d reply for the missing hook.
"""

from .healing_contract import declare_healing_rule
from .packet_module import build_packet_module, full_plus_reduced_parser

PACKET_SHA256 = "1795828f6486a1da27c639b301d6ebca7047735f17a173075d41d59369c82942"

# Prowling Projectile's missile "deals magic damage to the first enemy hit.
# If the target is a champion, they are also revealed and slowed by 20% for
# 1 second"; Final Chapter's waves hit enemies who "take magic damage and
# are slowed by 10% for 1.25 seconds".  W (You and Me!) and E (Zoomies) are
# out_of_scope ally rows and P heals — none authors a damage part.
MODULE_CC = {"Q": "slow", "R": "slow"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Yuumi",
    PACKET_SHA256,
    assumption_overrides=(
        "Final Chapter prices all 5 waves (Magic Damage per Hit + 4 x "
        "Reduced Damage per Hit == Total Magic Damage).",
    ),
    # Q is one missile hitting one enemy; the packet has no travel phase
    # to place.
    single_hit_slots=frozenset({"Q"}),
    cc_kinds=MODULE_CC,
    slot_parsers={
        "R": full_plus_reduced_parser(
            full_attr="Magic Damage per Hit",
            reduced_attr="Reduced Damage per Hit",
            dmg_type="magic",
            reduced_count=4,
            time_offset=0.7,
            hit_interval=0.7,
            dot_duration=3.5,
        )
    },
)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E", "R"} else "out_of_scope") for slot in "PQWER"
}

SELF_HEALING_RULE = declare_healing_rule("Yuumi")
