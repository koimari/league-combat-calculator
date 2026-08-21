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
    assert set(abilities) == set(expected) | {"passive"}
    for slot, raw in expected.items():
        assert parts_raw_total(abilities[slot]["parts"], "magic") == pytest.approx(raw)


class TestPassive:
    """P (Iceborn Subjugation) emits a zero-damage boundary receipt."""

    def test_passive_emits_zero_damage_row(self, lissandra_data, parse_at) -> None:
        _, abilities = parse_at(
            lissandra_data,
            18,
            ap=200,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        )
        assert abilities["passive"]["name"] == "Iceborn Subjugation"
        assert abilities["passive"]["total_raw"] == pytest.approx(0.0)
        assert abilities["passive"]["parts"] == ()
        assert abilities["passive"]["damage_type"] == "magic"
        # Sourced would-be shatter magnitude at level 18 ("Per-Level
        # Scaling" cached leveling row), reported for traceability only.
        assert "520" in abilities["passive"]["detail"]


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
