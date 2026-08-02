"""Revision-backed tests for Lissandra's direct-damage slot map."""

import pytest

from src.calculator.ability_spec import parts_raw_total


def test_lissandra_full_rotation_uses_each_direct_hit(lissandra_data, parse_at):
    _, abilities = parse_at(
        lissandra_data,
        18,
        ap=200,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
    )

    expected = {"Q": 370.0, "W": 350.0, "E": 330.0, "R": 500.0}
    assert set(abilities) == set(expected)
    for slot, raw in expected.items():
        assert parts_raw_total(abilities[slot]["parts"], "magic") == pytest.approx(raw)


def test_lissandra_rotation_is_mitigated_and_resource_ordered(
    lissandra_data, parse_at, fight
):
    stats, abilities = parse_at(
        lissandra_data,
        18,
        ap=200,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
    )
    result = fight(stats, abilities, target_magic_resistance=100)

    assert result["total_damage"] == pytest.approx(775.0)
    assert [event["slot"] for event in result["cast_timeline"]] == [
        "Q",
        "W",
        "E",
        "R",
    ]
    assert sum(ability["resource_cost"] for ability in abilities.values()) == 315.0
    assert stats["max_mana"] >= 315.0
