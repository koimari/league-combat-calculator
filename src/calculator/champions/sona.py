"""Sona — CP10.8 full-entry-reviewed packet module.

E8d ally-support: W (Aria of Perseverance) heals and shields the caster and
one selected teammate.  The event is authored by the engine's ally-support
scanner from the cached W leveling (Heal 30-90 + 30% AP; Shield Strength
25-105 + 25% AP; scope self_and_one_teammate) at the W cast time; the module
declares W in SLOTS so the fight rotation casts it.
"""

from .packet_module import build_packet_module

PACKET_SHA256 = "c78392f6b8f667c85594d31be2e6a9c1b7c6504d5cd02e3c5b385271dafc6c06"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Sona", PACKET_SHA256
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
    """Resolve Sona self-healing events from its authored packet."""
    healing = []
    w_rank = _healing._rank(ability_damages, "W")
    heal = _healing.extract_named(
        _healing._ability(champion_data, "W"), "Heal", w_rank, champion_stats
    )
    if heal > 0.0:
        for cast_index, cast in enumerate(cast_timeline or []):
            if cast.get("slot") != "W":
                continue
            healing.append(
                {
                    "time": float(cast.get("time", 0.0)),
                    "amount": heal,
                    "source": "Aria of Perseverance",
                    "kind": "champion_ability",
                    "actor_wide": True,
                    "target_scope": "self_and_one_teammate",
                    "_event_id": f"sona:w:{cast_index}",
                }
            )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Sona", derive_self_healing)
