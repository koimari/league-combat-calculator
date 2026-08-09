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
    """Resolve Nami self-healing events from its authored packet."""
    healing = []
    w_rank = _healing._rank(ability_damages, "W")
    w_ability = _healing._ability(champion_data, "W")
    base = _healing.extract_named(w_ability, "Heal", w_rank, champion_stats, {})
    floor = _healing.extract_named(
        w_ability, "Minimum Heal", w_rank, champion_stats, {}
    )
    ap = float(champion_stats.get("ability_power", 0.0) or 0.0)
    amount = max(floor, base * (0.80 + 0.15 * ap / 100.0))
    for event in _healing._attributed_events(
        damage_events, lambda source, _event: source == "W"
    ):
        _healing._heal_from_damage(
            healing, event, amount, "Ebb and Flow", link_to_damage=False
        )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Nami", derive_self_healing)
