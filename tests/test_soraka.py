"""Revision-backed tests for Soraka's offensive slot map."""

import pytest

from src.calculator.ability_spec import parts_raw_total


def _parse(soraka_data, parse_at, second_hit):
    return parse_at(
        soraka_data,
        18,
        ap=200,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_options={"e_second_hit": second_hit},
    )


def test_soraka_e_counts_initial_hit_and_eruption(soraka_data, parse_at):
    _, abilities = _parse(soraka_data, parse_at, True)

    # E8d: W (Astral Infusion) is now declared as a zero-damage support cast
    # so the ally-support scanner can emit its sourced heal.
    assert set(abilities) == {"Q", "W", "E"}
    assert abilities["W"]["total_raw"] == 0.0
    assert abilities["W"]["parts"] == ()
    assert parts_raw_total(abilities["Q"]["parts"], "magic") == pytest.approx(295.0)
    assert parts_raw_total(abilities["E"]["parts"], "magic") == pytest.approx(500.0)
    assert abilities["E"]["dot_duration"] == 1.5
    assert abilities["E"]["detail"] == "Initial hit + eruption"


def test_soraka_e_can_exclude_eruption(soraka_data, parse_at):
    _, abilities = _parse(soraka_data, parse_at, False)

    assert parts_raw_total(abilities["E"]["parts"], "magic") == pytest.approx(250.0)
    assert "dot_duration" not in abilities["E"]
    assert abilities["E"]["detail"] == "Initial hit only"


def test_soraka_rotation_spends_only_offensive_spell_costs(
    soraka_data, parse_at, fight
):
    stats, abilities = _parse(soraka_data, parse_at, True)
    result = fight(stats, abilities, target_magic_resistance=100)

    assert result["total_damage"] == pytest.approx(397.5)
    # E8d: W (Astral Infusion) joins the rotation as a zero-damage support cast.
    assert [event["slot"] for event in result["cast_timeline"]] == ["Q", "W", "E"]
    assert abilities["Q"]["resource_cost"] + abilities["E"]["resource_cost"] == 155.0
    assert stats["max_mana"] >= 155.0
