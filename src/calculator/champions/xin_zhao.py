"""Xin Zhao — CP10.10 full-entry-reviewed packet module."""

from .packet_module import build_packet_module

PACKET_SHA256 = "c39efd0eac006d4b59799a0b3c5de44ef6ec31f9f9a23bea7ab8a25d2f4ccf64"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Xin Zhao", PACKET_SHA256, single_hit_slots=frozenset({"R"})
)
PACKET_SPEC = SLOTS.packet_spec
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
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
    """Resolve Xin Zhao self-healing events from its authored packet."""
    healing = []
    lifesteal = float(champion_stats.get("lifesteal_percent", 0.0) or 0.0)
    if lifesteal > 0.0:
        for event in _healing._attributed_events(
            damage_events, lambda source, _event: source == "W"
        ):
            amount = (
                0.333 * max(0.0, float(event.get("damage", 0.0))) * lifesteal / 100.0
            )
            _healing._heal_from_damage(healing, event, amount, "Wind Becomes Lightning")
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Xin Zhao", derive_self_healing)
