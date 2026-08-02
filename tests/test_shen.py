"""Reference, resource, and event-order tests for Shen's sourced module."""

import pytest

from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.stats import calculate_total_stats


def _stats(shen_data, level: int = 12) -> dict:
    stats = calculate_total_stats(shen_data, level, [])
    stats.update(
        {
            "health": stats["health"] + 1000.0,
            "bonus_health": 1000.0,
            "attack_damage": 100.0,
            "base_attack_damage": 100.0,
            "bonus_attack_damage": 0.0,
            "ability_power": 100.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 1.0,
            "move_speed": 340.0,
        }
    )
    return stats


def _parse(shen_data, *, enhanced=True, hits=3):
    stats = _stats(shen_data)
    abilities = parse_champion_abilities(
        shen_data,
        12,
        100.0,
        ability_ranks={"Q": 5, "W": 1, "E": 3, "R": 2},
        champion_stats=stats,
        target_stats={
            "target_max_health": 2500.0,
            "target_current_health": 2500.0,
            "target_missing_health": 0.0,
        },
        champion_options={
            "q_spirit_blade_hit": enhanced,
            "q_attacks_landed": hits,
            "q_first_attack_delay": 0.5,
            "e_dash_distance": 600.0,
        },
    )
    return stats, abilities


def test_reference_q_and_e_formulas(shen_data):
    """Level 12, rank-5 Q, 100 AP, 1,000 bonus HP, 2,500 target HP."""
    _, enhanced = _parse(shen_data)
    _, normal = _parse(shen_data, enhanced=False)

    # Level flat 29.4118 + enhanced (7% + 2% per 100 AP) max HP.
    assert enhanced["Q"]["total_raw"] == pytest.approx(763.235294)
    # Same flat + normal (4% + 1.5% per 100 AP) max HP.
    assert normal["Q"]["total_raw"] == pytest.approx(500.735294)
    # Rank-3 E: 110 + 11% of 1,000 bonus HP.
    assert enhanced["E"]["total_raw"] == pytest.approx(220.0)


def test_options_control_hit_count_timing_and_dash(shen_data):
    _, abilities = _parse(shen_data, hits=2)

    assert abilities["Q"]["total_raw"] == pytest.approx(508.823529)
    timing = abilities["Q"]["empowers_next_auto"]["authored_timing"]
    assert timing["first_attack_delay"] == pytest.approx(0.5)
    assert timing["attack_interval"] == pytest.approx(2.0 / 3.0)
    assert abilities["E"]["parts"][0].time_offset == pytest.approx(600 / 1140)
    assert abilities["E"]["cooldown"] == pytest.approx(14 + 600 / 1140)


def test_one_rotation_forces_and_orders_q_attacks(shen_data):
    stats, abilities = _parse(shen_data)
    result = calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=2500.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=5.0,
            one_rotation=True,
            deterministic=True,
            enforce_resource_limits=True,
            cast_order=("E", "Q"),
        ),
    )

    # E 220 + Q bonus 763.235 + three 100-AD attacks.
    assert result["total_damage"] == pytest.approx(1283.235294)
    assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(1063.235294)
    assert result["breakdown"]["Q"]["damage_by_type"] == pytest.approx(
        {"magic": 763.235294, "physical": 300.0}
    )
    q_events = result["breakdown"]["Q"]["damage_events"]
    assert len(q_events) == 6
    assert sorted({event["time"] for event in q_events}) == pytest.approx(
        [0.5, 0.5 + 2.0 / 3.0, 0.5 + 4.0 / 3.0]
    )
    assert sum(event["damage"] for event in q_events) == pytest.approx(
        result["breakdown"]["Q"]["total_damage"]
    )
    assert result["resource_spent"] == pytest.approx(250.0)
    assert result["resource_remaining"] == pytest.approx(350.0)
    assert result["timeline_coverage"]["complete"] is True


def test_public_pipeline_splits_q_swing_from_magic_rider(shen_data):
    result = run_fight(
        shen_data,
        12,
        [],
        FightParams(
            target_health=2500.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=5.0,
            one_rotation=True,
            ability_ranks={"Q": 5, "W": 1, "E": 3, "R": 2},
            champion_options={
                "q_spirit_blade_hit": True,
                "q_attacks_landed": 3,
                "q_first_attack_delay": 0.5,
                "e_dash_distance": 600.0,
            },
        ),
    )

    assert result["damage_by_type"]["physical"] == pytest.approx(392.0)
    assert result["damage_by_type"]["magic"] == pytest.approx(613.235294)
    assert sum(result["damage_by_type"].values()) == pytest.approx(
        result["total_damage"]
    )


def test_timed_auto_stream_is_explicitly_partial(shen_data):
    stats, abilities = _parse(shen_data)
    result = calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=2500.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            one_rotation=False,
            deterministic=True,
            cast_order=("E", "Q"),
        ),
    )

    coverage = result["timeline_coverage"]
    assert coverage["complete"] is False
    assert coverage["certification"] == "partial_event_order"
    assert "Q" in coverage["coarse_sources"]
    assert "ambient auto stream" in coverage["note"]


def test_target_max_health_change_fails_closed(shen_data):
    params = FightParams(
        target_health=2500.0,
        target_armor=0.0,
        target_magic_resistance=0.0,
        fight_duration_seconds=5.0,
        one_rotation=True,
        ability_ranks={"Q": 5, "W": 1, "E": 3, "R": 2},
        champion_options={
            "q_spirit_blade_hit": True,
            "q_attacks_landed": 3,
            "q_first_attack_delay": 0.5,
            "e_dash_distance": 600.0,
        },
        target_threshold_health_bonus=200.0,
        target_threshold_health_heal=300.0,
        target_threshold_health_ratio=0.3,
        target_threshold_health_duration=5.0,
    )

    with pytest.raises(ValueError, match="Protoplasm Harness"):
        run_fight(shen_data, 12, [], params)
