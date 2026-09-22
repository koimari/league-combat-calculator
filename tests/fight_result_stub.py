"""One display-mode fight result, the shape ``serialize_fight_result`` reads.

Three suites drive the public serializers over a hand-built result, and
built in three places the shape drifted: one stub carried 30 of the 31 keys
``pipeline.run_fight`` stamps outside score mode, and the serializer read the
missing one through a literal default, so nothing failed. It is one builder
here, and each caller overrides only what its own assertion is about.

Nothing pins this list: the serializer does. Every field it reads is
required, so a result short one key raises naming it, and this stub is
checked by every test that passes it in.
"""

from typing import Any


def fight_result(**overrides: Any) -> dict[str, Any]:
    """A result carrying every field the display path publishes, all at rest."""
    return {
        "champion_stats": {},
        "total_damage": 0.0,
        "health_damage": 0.0,
        "shield_absorbed": 0.0,
        "magic_shield_absorbed": 0.0,
        "physical_shield_absorbed": 0.0,
        "general_shield_absorbed": 0.0,
        "threshold_shield_absorbed": 0.0,
        "threshold_health_triggered": False,
        "threshold_health_bonus_gained": 0.0,
        "target_healing_received": 0.0,
        "target_ending_health": 0.0,
        "target_effective_max_health": 0.0,
        "ability_damage": 0.0,
        "auto_attack_damage": 0.0,
        "damage_by_type": {},
        "breakdown": {},
        "effective_mr": 0.0,
        "effective_armor": 0.0,
        "notes": [],
        "cast_timeline": [],
        "rotation": {},
        "resource_spent": 0.0,
        "resource_remaining": 0.0,
        "resource_ledger": {},
        "timeline_coverage": {
            "complete": True,
            "certification": "event_order_certified",
            "exact_sources": [],
            "coarse_sources": [],
        },
        "auto_attack_policy": {},
        "auto_attack_schedule": {},
        "damage_events": [],
        "self_healing": 0.0,
        "self_healing_events": [],
        **overrides,
    }
