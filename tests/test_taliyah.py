"""Revision-backed formulas, state controls, and event order for Taliyah."""

import pytest

from src.calculator.ability_spec import parts_raw_total
from src.calculator.champions import (
    get_champion_cast_order,
    get_champion_options_meta,
)

RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _parse(taliyah_data, parse_at, *, ground="normal", detonations=4, distance=800):
    return parse_at(
        taliyah_data,
        18,
        ap=200,
        ability_ranks=RANKS,
        champion_options={
            "q_ground": ground,
            "e_detonations": detonations,
            "q_target_distance": distance,
        },
    )


def _parse_roster_target(taliyah_data, parse_at, target_index):
    return parse_at(
        taliyah_data,
        18,
        ap=200,
        ability_ranks=RANKS,
        target_stats={
            "target_max_health": 2500.0,
            "roster_target_index": float(target_index),
            "roster_target_count": 2.0,
        },
        champion_options={
            "q_ground": "worked",
            "e_detonations": 4,
            "q_target_distance": 800,
        },
    )


def test_normal_volley_and_four_stone_combo_use_sourced_formulas(
    taliyah_data, parse_at
):
    _, abilities = _parse(taliyah_data, parse_at)

    # Q5 @ 200 AP: first 225, then 4 x 90 = 585.
    assert parts_raw_total(abilities["Q"]["parts"], "magic") == pytest.approx(585.0)
    assert len(abilities["Q"]["parts"]) == 5
    # E5 @ 200 AP: 360 initial + 145 x (1 + .75 + .5 + .25).
    assert parts_raw_total(abilities["E"]["parts"], "magic") == pytest.approx(722.5)
    assert abilities["W"]["parts"] == ()
    assert abilities["W"]["total_raw"] == 0.0


def test_stone_count_is_explicit_and_never_exceeds_four(taliyah_data, parse_at):
    _, none = _parse(taliyah_data, parse_at, detonations=0)
    _, two = _parse(taliyah_data, parse_at, detonations=2)
    _, clamped = _parse(taliyah_data, parse_at, detonations=99)

    assert parts_raw_total(none["E"]["parts"]) == pytest.approx(360.0)
    assert parts_raw_total(two["E"]["parts"]) == pytest.approx(360.0 + 145.0 * 1.75)
    assert parts_raw_total(clamped["E"]["parts"]) == pytest.approx(722.5)


def test_worked_ground_changes_damage_cost_cooldown_and_projectile(
    taliyah_data, parse_at
):
    _, normal = _parse(taliyah_data, parse_at, ground="normal", distance=1000)
    _, worked = _parse(taliyah_data, parse_at, ground="worked", distance=1000)

    assert parts_raw_total(worked["Q"]["parts"], "magic") == pytest.approx(405.0)
    assert worked["Q"]["resource_cost"] == pytest.approx(10.0)
    assert worked["Q"]["cooldown"] == pytest.approx(1.5)
    assert normal["Q"]["resource_cost"] == pytest.approx(75.0)
    assert normal["Q"]["cooldown"] == pytest.approx(3.0)
    assert len(worked["Q"]["parts"]) == 1
    assert worked["Q"]["parts"][0].time_offset == pytest.approx(1.225)


def test_worked_boulder_uses_primary_and_secondary_target_formulas(
    taliyah_data, parse_at
):
    _, primary = _parse_roster_target(taliyah_data, parse_at, 0)
    _, secondary = _parse_roster_target(taliyah_data, parse_at, 1)

    assert parts_raw_total(primary["Q"]["parts"]) == pytest.approx(405.0)
    assert parts_raw_total(secondary["Q"]["parts"]) == pytest.approx(225.0)
    assert "primary target" in primary["Q"]["detail"]
    assert "secondary target" in secondary["Q"]["detail"]


def test_rotation_is_resource_legal_and_event_order_certified(
    taliyah_data, parse_at, fight
):
    stats, abilities = _parse(taliyah_data, parse_at)
    result = fight(
        stats,
        abilities,
        target_magic_resistance=100,
        cast_order=get_champion_cast_order("Taliyah"),
        enforce_resource_limits=True,
    )

    assert get_champion_cast_order("Taliyah") == ["E", "W", "Q"]
    assert [event["slot"] for event in result["cast_timeline"]] == [
        "E",
        "W",
        "Q",
    ]
    assert result["resource_spent"] == pytest.approx(165.0)
    assert result["resource_remaining"] == pytest.approx(stats["max_mana"] - 165.0)
    assert result["total_damage"] == pytest.approx((722.5 + 585.0) / 2.0)
    assert result["timeline_coverage"]["complete"] is True
    assert result["timeline_coverage"]["certification"] == "event_order_certified"
    assert result["timeline_coverage"]["exact_sources"] == ["E", "Q"]


def test_public_metadata_exposes_state_without_timed_overclaim():
    meta = get_champion_options_meta("Taliyah")

    assert {option["key"] for option in meta["options"]} == {
        "q_ground",
        "e_detonations",
        "q_target_distance",
    }
    assert meta["supported_fight_modes"] == ["one_rotation"]
    assert len(meta["sources"]) == 5
