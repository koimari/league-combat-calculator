"""Trundle — CP10.8 full-entry-reviewed packet module."""

from .packet_module import build_packet_module, repeat_damage_parser

PACKET_SHA256 = "0346556b3577caf70cd1fadf59cbec2eb38d07d723625a473330e5c2618b0d4b"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Trundle",
    PACKET_SHA256,
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
REVIEW_STATUS = "reviewed_module"
