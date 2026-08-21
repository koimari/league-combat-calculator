"""Regression coverage for the all-champion reviewed packet lane."""

import pytest

from src.calculator.champions import (
    _CHAMPION_MODULES,
    engine_registration_kind,
    parse_champion_abilities,
    registered_champion_names,
)
from src.calculator.data_fetcher import get_champion
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.stats import calculate_total_stats


def _stats(name: str, level: int = 6):
    champion = get_champion(name)
    stats = calculate_total_stats(champion, level, [])
    return champion, stats


#: The shapes a parsed row may take.  A row carrying none of them is a slot
#: the engine would price as nothing at all.
VALUE_KEYS = (
    "parts",
    "on_hit",
    "double_shot",
    "auto_attack_conversion",
    "stat_buff",
    "no_damage",
)


@pytest.mark.parametrize(
    "level, ability_ranks",
    [(6, None), (18, {"Q": 5, "W": 5, "E": 5, "R": 3})],
    ids=["early", "max_rank"],
)
def test_all_registered_modules_parse_without_a_generic_runtime_fallback(
    level, ability_ranks
):
    """Every name resolves to its own reviewed module and prices every row it
    authors, at the first ultimate rank and again at the maxed kit."""
    for name in registered_champion_names():
        assert name in _CHAMPION_MODULES
        assert engine_registration_kind(name) == "reviewed_module", name
        champion, stats = _stats(name, level)
        result = parse_champion_abilities(
            champion,
            level,
            stats["ability_power"],
            ability_ranks=ability_ranks,
            champion_stats=stats,
            target_stats={
                "target_max_health": 1000.0,
                "target_current_health": 1000.0,
                "target_missing_health": 0.0,
            },
        )
        assert isinstance(result, dict), name
        assert result, name
        assert all(
            any(key in entry for key in VALUE_KEYS) for entry in result.values()
        ), name


def test_mundo_q_uses_running_current_health_and_floor():
    champion, stats = _stats("DrMundo")
    params = FightParams.from_request(
        {
            "target_health": 2400,
            "target_armor": 0,
            "target_mr": 0,
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": False,
            "auto_attack_uptime": 0,
            "ability_ranks": {"Q": 5, "W": 0, "E": 0, "R": 0},
        }
    )
    result = run_fight(champion, 10, [], params)
    q = result["breakdown"]["Q"]
    assert q["casts"] == 3
    # Rank 5 is 30% current health: 720 + 504 + 352.8.
    assert q["total_damage"] == pytest.approx(1576.8)


def test_jinx_weapon_changes_auto_damage_without_changing_spell_packet():
    champion, stats = _stats("Jinx")
    target = {"target_max_health": 1000.0, "target_current_health": 1000.0}
    minigun = parse_champion_abilities(
        champion,
        6,
        0,
        champion_stats=stats,
        target_stats=target,
        champion_options={"jinx_weapon": "minigun", "jinx_rev_up_stacks": 3},
    )
    rocket = parse_champion_abilities(
        champion,
        6,
        0,
        champion_stats=stats,
        target_stats=target,
        champion_options={"jinx_weapon": "rocket", "jinx_rev_up_stacks": 0},
    )
    assert minigun["Q"]["stat_buff"]["bonus_attack_speed"] > 0
    assert rocket["Q"]["auto_attack_override"]["damage_ratio"] == pytest.approx(1.10)


def test_aphelios_onslaught_scales_hit_count_from_bonus_attack_speed():
    champion, stats = _stats("Aphelios")
    target = {"target_max_health": 1000.0, "target_current_health": 1000.0}
    low = parse_champion_abilities(
        champion,
        6,
        0,
        champion_stats=stats,
        target_stats=target,
        champion_options={
            "aphelios_main_weapon": "severum",
            "aphelios_bonus_as_points": 0,
        },
    )
    high = parse_champion_abilities(
        champion,
        6,
        0,
        champion_stats=stats,
        target_stats=target,
        champion_options={
            "aphelios_main_weapon": "severum",
            "aphelios_bonus_as_points": 6,
        },
    )
    assert low["Q"]["parts"][0].count == 6
    assert high["Q"]["parts"][0].count > low["Q"]["parts"][0].count
    assert high["Q"]["total_raw"] > low["Q"]["total_raw"]
