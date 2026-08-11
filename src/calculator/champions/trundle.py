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

from .. import healing_helpers as _healing  # pylint: disable=wrong-import-position


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument,wrong-import-position
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Trundle self-healing events from its authored packet."""
    healing = []
    for event in _healing._attributed_events(
        damage_events, lambda source, _event: source == "R"
    ):
        dealt = float(event.get("raw_damage", event.get("damage", 0.0)) or 0.0)
        _healing._heal_from_damage(
            healing, event, dealt, "Subjugate", link_to_damage=False
        )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Trundle", derive_self_healing)
