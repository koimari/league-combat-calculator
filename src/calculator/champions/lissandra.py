"""Lissandra — revision-backed direct-damage slot map.

Q, W, E, and R each deal one sourced magic-damage instance. E's recast only
moves Lissandra, while R's ice field deals the same damage whether she targets
herself or an enemy.

Coverage: P (Iceborn Subjugation) is out of scope twice over. It needs a
nearby champion death, which the selected fight does not invent, and what
it raises is a Frozen Thrall — a summoned pet on its own timeline, an
axis the engine does not have.
"""

from typing import Any

from .engine import build_parser
from .. import healing_helpers as _healing
from .healing_contract import declare_healing_rule
from .slotlib import simple_damage, with_control
from .source_receipts import load_champion_sources

OPTIONS: list[dict[str, Any]] = []

ASSUMPTIONS = [
    "Iceborn Subjugation is excluded because no champion death is assumed.",
    "Glacial Path counts its outward hit; the recast is movement only.",
    "Frozen Tomb counts one ice-field hit, whether cast on Lissandra or an enemy.",
]

SOURCES = load_champion_sources("Lissandra")

# Each slot deals its one sourced instance at the cast (the module
# docstring's own claim), so each certifies that boundary — which is what
# carries MODULE_CC's reviewed kinds into the event ledger.
SLOTS = {
    "Q": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    # Ring of Frost carries its sourced root duration onto the hit.
    "W": with_control(
        simple_damage(
            attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
        ),
        kind="root",
        duration_attr="Root Duration",
    ),
    "E": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "R": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
}

# Cached kit review: Q "slows enemies hit for 1.5 seconds", W deals damage
# "and root[s] them for a duration", E's claw only decelerates itself, and
# the R instance this module prices is the ice field, which deals damage
# "and slow[s] them for 0.5 seconds" on either cast — the enemy cast's
# 1.5-second stun is not the hit the module counts (ASSUMPTIONS above).
MODULE_CC = {"Q": "slow", "W": "root", "E": "none", "R": "slow"}

parse_abilities = build_parser(SLOTS, "Lissandra", cc_kinds=MODULE_CC)


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
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
    for payment in _healing._payments(
        _healing.HealAnchor.CAST_SCHEDULE, "R", damage_events, cast_timeline
    ):
        trigger = _healing._trigger_fields(payment.event)
        for index in range(1, 11):
            healing.append(
                {
                    "time": payment.cast_time + index * 0.25,
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


SELF_HEALING_RULE = declare_healing_rule("Lissandra", derive_self_healing)
