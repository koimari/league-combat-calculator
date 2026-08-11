"""Lissandra — revision-backed direct-damage slot map.

Q, W, E, and R each deal one sourced magic-damage instance. E's recast only
moves Lissandra, while R's ice field deals the same damage whether she targets
herself or an enemy. Iceborn Subjugation is excluded because it requires a
champion death; the selected fight does not invent one.
"""

from typing import Any

from .engine import build_parser
from .slotlib import simple_damage, with_control

OPTIONS: list[dict[str, Any]] = []

ASSUMPTIONS = [
    "Iceborn Subjugation is excluded because no champion death is assumed.",
    "Glacial Path counts its outward hit; the recast is movement only.",
    "Frozen Tomb counts one ice-field hit, whether cast on Lissandra or an enemy.",
]

SOURCES = [
    {
        "label": "Ice Shard",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Lissandra/Ice_Shard",
        "revision_id": 4007664,
        "revision_timestamp": "2026-04-12T10:26:56Z",
    },
    {
        "label": "Ring of Frost",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Lissandra/Ring_of_Frost",
        "revision_id": 3936419,
        "revision_timestamp": "2025-07-24T17:33:52Z",
    },
    {
        "label": "Glacial Path",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Lissandra/Glacial_Path",
        "revision_id": 4007666,
        "revision_timestamp": "2026-04-12T10:34:41Z",
    },
    {
        "label": "Frozen Tomb",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Lissandra/Frozen_Tomb",
        "revision_id": 4017996,
        "revision_timestamp": "2026-05-14T13:55:57Z",
    },
]

SLOTS = {
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "W": with_control(
        simple_damage(attr="Magic Damage", dmg_type="magic"),
        kind="root",
        duration_attr="Root Duration",
    ),
    "E": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "R": simple_damage(attr="Magic Damage", dmg_type="magic"),
}

parse_abilities = build_parser(SLOTS, "Lissandra")


# Authoritative review metadata (issue #161).
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
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
    """Resolve Lissandra self-healing events from its authored packet."""
    healing = []
    r = _healing._ability(champion_data, "R")
    r_rank = _healing._rank(ability_damages, "R")
    min_tick = _healing.extract_named(
        r, "Minimum Heal per Tick", r_rank, champion_stats
    )
    max_tick = _healing.extract_named(
        r, "Maximum Heal per Tick", r_rank, champion_stats
    )
    for event in _healing._attributed_events(
        damage_events, lambda source, _event: source == "R"
    ):
        trigger = _healing._trigger_fields(event)
        for index in range(1, 11):
            healing.append(
                {
                    "time": float(event.get("time", 0.0)) + index * 0.25,
                    "amount": 0.0,
                    "amount_formula": _healing._missing_health_scaled_heal(
                        min_tick, max_tick
                    ),
                    "source": "Frozen Tomb",
                    "kind": "champion_ability",
                    **trigger,
                }
            )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Lissandra", derive_self_healing)
