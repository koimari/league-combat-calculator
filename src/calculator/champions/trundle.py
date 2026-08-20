"""Trundle — CP10.8 full-entry-reviewed packet module."""

from .packet_module import build_packet_module, repeat_damage_parser

PACKET_SHA256 = "0346556b3577caf70cd1fadf59cbec2eb38d07d723625a473330e5c2618b0d4b"

# Reviewed crowd control, read from the cached kit.  Q (Chomp) empowers
# one attack to "deal bonus physical damage and slow the target by 75% for
# 0.1 seconds".  R (Subjugate) "deal[s] magic damage and heal[s] himself
# for the same amount" and reduces resistances and size — real debuffs,
# but none of them crowd control.  W (Frozen Domain) and E (Pillar of Ice)
# carry the kit's other control and deal no damage.
MODULE_CC = {"Q": "slow", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Trundle",
    PACKET_SHA256,
    # Chomp is one empowered basic attack, so its row is one blow the
    # ledger can time; Subjugate already authors its 8 drain ticks.
    single_hit_slots=frozenset({"Q"}),
    cc_kinds=MODULE_CC,
    assumption_overrides=(
        "Subjugate prices the full 4-second drain: Magic Damage Per Second "
        "x 8 == Total Magic Damage / Total Healing at every rank.",
    ),
    slot_parsers={
        "R": repeat_damage_parser(
            attr="Magic Damage Per Second",
            dmg_type="magic",
            count=8,
            time_offset=0.5,
            hit_interval=0.5,
            dot_duration=4.0,
            name="Subjugate",
        )
    },
)
PACKET_SPEC = SLOTS.packet_spec
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "R"} else "out_of_scope") for slot in "PQWER"
}

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Trundle")
