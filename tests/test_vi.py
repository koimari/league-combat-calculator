"""Reference, ordering, multi-target, and fail-closed tests for Vi."""

import pytest

from src import app as app_module
from src.calculator.champions import (
    get_champion_cast_order,
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.pipeline import FightParams, run_fight

RANKS = {"Q": 5, "W": 3, "E": 3, "R": 2}


def _stats() -> dict[str, float]:
    return {
        "health": 2000.0,
        "bonus_health": 0.0,
        "attack_damage": 200.0,
        "base_attack_damage": 100.0,
        "bonus_attack_damage": 100.0,
        "ability_power": 0.0,
        "armor": 50.0,
        "magic_resistance": 50.0,
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.644,
        "critical_strike_chance": 0.0,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "flat_armor_penetration": 0.0,
        "armor_penetration_percent": 0.0,
        "lethality": 0.0,
        "ability_haste": 0.0,
        "max_mana": 2000.0,
        "bonus_mana": 0.0,
        "basic_ability_haste": 0.0,
        "is_melee": True,
        "level": 18,
    }


def _abilities(vi_data, *, starting_stacks=0, target_index=0, charge=1.25):
    stats = _stats()
    return stats, parse_champion_abilities(
        vi_data,
        18,
        0.0,
        ability_ranks=RANKS,
        champion_stats=stats,
        target_stats={
            "target_max_health": 2500.0,
            "target_current_health": 2500.0,
            "roster_target_index": float(target_index),
            "roster_target_count": 2.0,
        },
        champion_options={
            "q_charge_seconds": charge,
            "q_dash_distance": 725.0,
            "denting_blows_starting_stacks": starting_stacks,
            "e_attack_delay": 0.25,
            "r_start_distance": 800.0,
        },
    )


def _fight(stats, abilities):
    return calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=2500.0,
            target_armor=100.0,
            target_magic_resistance=100.0,
            fight_duration_seconds=5.0,
            one_rotation=True,
            deterministic=True,
            enforce_resource_limits=True,
            cast_order=get_champion_cast_order("Vi"),
        ),
    )


def test_reference_formulas_and_full_charge(vi_data):
    stats, abilities = _abilities(vi_data, starting_stacks=2)

    # Q5 minimum is 120 + 60% bonus AD = 180; full charge multiplies
    # the complete minimum formula by 2.5 -> 450.
    assert abilities["Q"]["total_raw"] == pytest.approx(450.0)
    # E3 primary stores only its rider. The forced basic swing supplies
    # the other 100% AD: 50 + 10% AD = 70 rider, 270 modified attack.
    assert abilities["E"]["total_raw"] == pytest.approx(70.0)
    assert abilities["R"]["total_raw"] == pytest.approx(340.0)
    assert abilities["Q"]["parts"][0].time_offset == pytest.approx(
        1.25 + 725.0 / 1540.0
    )
    assert stats["attack_damage"] == 200.0


def test_q_charge_scales_continuously_and_clamps_range(vi_data):
    _, minimum = _abilities(vi_data, charge=0.0)
    _, half = _abilities(vi_data, charge=0.625)
    _, maximum = _abilities(vi_data, charge=1.25)

    assert minimum["Q"]["total_raw"] == pytest.approx(180.0)
    assert half["Q"]["total_raw"] == pytest.approx(315.0)
    assert maximum["Q"]["total_raw"] == pytest.approx(450.0)
    # At zero charge the requested 725 distance is capped to 250.
    assert minimum["Q"]["parts"][0].time_offset == pytest.approx(250 / 1450)


def test_q_triggered_w_uses_old_armor_then_shreds_later_hits(vi_data):
    stats, abilities = _abilities(vi_data, starting_stacks=2)
    result = _fight(stats, abilities)

    # At 100 armor: Q 225, W 118.75. W then reduces armor to 80, so
    # E is 270/1.8=150 and R is 340/1.8=188.8889.
    assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(225.0)
    assert result["breakdown"]["passive_proc_W"]["total_damage"] == pytest.approx(
        118.75
    )
    assert result["breakdown"]["E"]["total_damage"] == pytest.approx(150.0)
    assert result["breakdown"]["R"]["total_damage"] == pytest.approx(188.888889)
    assert result["total_damage"] == pytest.approx(682.638889)
    assert result["effective_armor"] == pytest.approx(80.0)


def test_e_triggered_w_shreds_only_r(vi_data):
    stats, abilities = _abilities(vi_data, starting_stacks=1)
    result = _fight(stats, abilities)

    assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(225.0)
    assert result["breakdown"]["E"]["total_damage"] == pytest.approx(135.0)
    assert result["breakdown"]["passive_proc_W"]["total_damage"] == pytest.approx(
        118.75
    )
    assert result["breakdown"]["R"]["total_damage"] == pytest.approx(188.888889)
    assert result["total_damage"] == pytest.approx(667.638889)
    assert result["effective_armor"] == pytest.approx(80.0)
    assert result["breakdown"]["passive_proc_W"]["damage_events"][0][
        "time"
    ] == pytest.approx(result["breakdown"]["E"]["damage_events"][0]["time"])


def test_incomplete_w_cycle_deals_no_fractional_proc(vi_data):
    stats, abilities = _abilities(vi_data, starting_stacks=0)
    result = _fight(stats, abilities)

    assert "passive_proc_W" not in result["breakdown"]
    assert result["total_damage"] == pytest.approx(530.0)
    assert result["effective_armor"] == pytest.approx(100.0)


def test_secondary_e_is_cone_damage_without_attack_or_w_stack(vi_data):
    stats, abilities = _abilities(vi_data, starting_stacks=1, target_index=1)
    result = _fight(stats, abilities)

    assert abilities["E"].get("empowers_next_auto") is None
    assert abilities["E"].get("applies_item_on_hits") is None
    assert "secondary cone target" in abilities["E"]["detail"]
    assert "passive_proc_W" not in result["breakdown"]
    assert result["breakdown"]["E"]["total_damage"] == pytest.approx(135.0)
    assert result["total_damage"] == pytest.approx(530.0)


def test_rotation_is_event_order_certified_and_resource_legal(vi_data):
    stats, abilities = _abilities(vi_data, starting_stacks=2)
    result = _fight(stats, abilities)

    assert result["resource_spent"] == pytest.approx(228.0)
    assert result["resource_remaining"] == pytest.approx(1772.0)
    assert result["timeline_coverage"]["complete"] is True
    assert result["timeline_coverage"]["certification"] == "event_order_certified"
    assert result["timeline_coverage"]["exact_sources"] == [
        "E",
        "Q",
        "R",
        "passive_proc_W",
    ]


def test_w_max_health_scaling_fails_closed_for_protoplasm(vi_data):
    params = FightParams(
        target_health=2500.0,
        target_armor=100.0,
        target_magic_resistance=100.0,
        fight_duration_seconds=5.0,
        one_rotation=True,
        ability_ranks={"Q": 5, "W": 1, "E": 3, "R": 1},
        champion_options={"denting_blows_starting_stacks": 2},
        target_threshold_health_bonus=200.0,
        target_threshold_health_heal=300.0,
        target_threshold_health_ratio=0.3,
        target_threshold_health_duration=5.0,
    )

    with pytest.raises(ValueError, match="Protoplasm Harness"):
        run_fight(vi_data, 10, [], params)


def test_timed_and_custom_order_requests_fail_closed():
    client = app_module.app.test_client()
    timed = client.post(
        "/api/calculate",
        json={"champion": "Vi", "level": 10, "fight_mode": "time_based"},
    )
    reordered = client.post(
        "/api/calculate",
        json={
            "champion": "Vi",
            "level": 10,
            "fight_mode": "one_rotation",
            "cast_order": ["E", "Q", "W", "R"],
        },
    )

    assert timed.status_code == 400
    assert "Time-based Vi calculations are withheld" in timed.get_json()["error"]
    assert reordered.status_code == 400
    assert "certified Q -> E -> R sequence" in reordered.get_json()["error"]


def test_one_rotation_compare_keeps_result_and_withholds_only_curve():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Vi",
            "level": 10,
            "fight_mode": "one_rotation",
            "include_crossover": True,
            "ability_ranks": {"Q": 5, "W": 1, "E": 3, "R": 1},
            "champion_options": {"denting_blows_starting_stacks": 2},
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total_damage"] > 0
    assert payload["comparison_curve"] == []
    assert payload["comparison_curve_status"]["available"] is False
    assert "withheld for Vi" in payload["comparison_curve_status"]["reason"]


def test_public_bis_returns_two_distinct_event_ordered_builds():
    response = app_module.app.test_client().post(
        "/api/optimize",
        json={
            "champion": "Vi",
            "level": 10,
            "fight_mode": "one_rotation",
            "target_health": 2500,
            "target_armor": 100,
            "target_mr": 50,
            "max_legendary_slots": 1,
            "ability_ranks": {"Q": 5, "W": 1, "E": 3, "R": 1},
            "champion_options": {"denting_blows_starting_stacks": 2},
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    ranked = payload["ranked_builds"]
    assert len(ranked) == 2
    assert (ranked[0]["items"], ranked[0]["boots"]) != (
        ranked[1]["items"],
        ranked[1]["boots"],
    )
    assert all(build["timeline_coverage"]["complete"] for build in ranked)
    assert payload["timeline_withheld_evaluations"] > 0
    assert payload["is_certified_best"] is False


def test_sources_and_options_are_public_revision_receipts():
    meta = get_champion_options_meta("Vi")

    assert len(meta["options"]) == 5
    assert meta["supported_fight_modes"] == ["one_rotation"]
    assert {row["revision_id"] for row in meta["sources"]} == {
        3986701,
        3921391,
        3932548,
        3986710,
        4004943,
    }
    assert all(
        row["url"].startswith("https://wiki.leagueoflegends.com/")
        for row in meta["sources"]
    )
