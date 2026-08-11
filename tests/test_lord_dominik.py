"""Lord Dominik's Regards target-context coverage."""

import pytest

from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.stats import calculate_total_stats


def test_level_14_rengar_ldr_against_ambessa_target_context() -> None:
    """Giant Slayer reads Ambessa's bonus health for Rengar's LDR fight."""
    rengar = get_champion("Rengar")
    ambessa = get_champion("Ambessa")
    rengar_items = [get_item_by_name("Lord Dominik's Regards")]
    ambessa_items = [
        get_item_by_name("Plated Steelcaps"),
        get_item_by_name("Spear of Shojin"),
        get_item_by_name("Sundered Sky"),
    ]

    ambessa_stats = calculate_total_stats(ambessa, 14, ambessa_items)
    # LDR's 35% is BONUS armor penetration (autoresearch pass 30): it only
    # cuts Ambessa's BONUS armor, so the fight needs her base/bonus split.
    base_armor = ambessa_stats["armor"] - ambessa_stats["bonus_armor"]
    params = FightParams(
        target_health=ambessa_stats["health"],
        target_bonus_health=ambessa_stats["bonus_health"],
        target_armor=ambessa_stats["armor"],
        target_bonus_armor=ambessa_stats["bonus_armor"],
        target_magic_resistance=ambessa_stats["magic_resistance"],
        target_basic_damage_multiplier=0.90,
        fight_duration_seconds=6.0,
        one_rotation=True,
        role="top",
    )

    result = run_fight(rengar, 14, rengar_items, params)
    amplifier = result["breakdown"]["damage_amp_Lord Dominik's Regards"]

    assert ambessa_stats["bonus_health"] == pytest.approx(850.0)
    assert amplifier["multiplier"] == pytest.approx(1.085)
    assert amplifier["total_damage"] == pytest.approx(
        result["total_damage"] * 0.085 / 1.085
    )
    # base armor untouched + bonus armor x 0.65
    assert result["effective_armor"] == pytest.approx(
        base_armor + ambessa_stats["bonus_armor"] * 0.65
    )
    assert {event["damage_type"] for event in amplifier["damage_events"]} == {
        "physical",
        "magic",
    }
