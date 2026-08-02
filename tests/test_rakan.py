"""Revision-backed tests for Rakan's offensive slot map."""

import pytest

from src.calculator.ability_spec import parts_raw_total


def test_rakan_rotation_counts_each_enemy_damage_cast_once(rakan_data, parse_at):
    _, abilities = parse_at(
        rakan_data,
        18,
        ap=200,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
    )

    expected = {"Q": 390.0, "W": 430.0, "R": 400.0}
    assert set(abilities) == set(expected)
    for slot, raw in expected.items():
        assert parts_raw_total(abilities[slot]["parts"], "magic") == pytest.approx(raw)


def test_rakan_rotation_is_mitigated_and_resource_ordered(rakan_data, parse_at, fight):
    stats, abilities = parse_at(
        rakan_data,
        18,
        ap=200,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
    )
    result = fight(stats, abilities, target_magic_resistance=100)

    assert result["total_damage"] == pytest.approx(610.0)
    assert [event["slot"] for event in result["cast_timeline"]] == ["Q", "W", "R"]
    assert sum(ability["resource_cost"] for ability in abilities.values()) == 235.0
    assert stats["max_mana"] >= 235.0


def test_rakan_quickness_hits_each_selected_target_once(rakan_data, parse_at, fight):
    stats, abilities = parse_at(
        rakan_data,
        18,
        ap=200,
        ability_ranks={"Q": 0, "W": 0, "E": 0, "R": 3},
    )

    first = fight(stats, abilities, target_magic_resistance=0)
    second = fight(stats, abilities, target_magic_resistance=100)

    assert first["total_damage"] == pytest.approx(400.0)
    assert second["total_damage"] == pytest.approx(200.0)
