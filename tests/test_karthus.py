"""Revision-backed formulas, resources, and target rules for Karthus."""

import pytest

from src.calculator.ability_spec import parts_raw_total
from src.calculator.champions import (
    get_champion_cast_order,
    get_champion_options_meta,
)

RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _parse(
    karthus_data,
    parse_at,
    *,
    wall=True,
    isolated=True,
    ticks=5,
    roster_count=1,
):
    return parse_at(
        karthus_data,
        18,
        ap=200,
        ability_ranks=RANKS,
        target_stats={
            "target_max_health": 2500.0,
            "roster_target_count": float(roster_count),
        },
        champion_options={
            "wall_contact": wall,
            "q_isolated": isolated,
            "e_ticks": ticks,
        },
    )


def test_alive_rotation_uses_isolated_q_selected_e_ticks_and_channelled_r(
    karthus_data, parse_at
):
    _, abilities = _parse(karthus_data, parse_at)

    # Q5 isolated @ 200 AP: 232 + 140 = 372.
    assert parts_raw_total(abilities["Q"]["parts"], "magic") == pytest.approx(372.0)
    # E5 per tick @ 200 AP: 27.5 + 10 = 37.5; five ticks.
    assert parts_raw_total(abilities["E"]["parts"], "magic") == pytest.approx(187.5)
    assert len(abilities["E"]["parts"]) == 5
    # R3 @ 200 AP: 500 + 140 = 640.
    assert parts_raw_total(abilities["R"]["parts"], "magic") == pytest.approx(640.0)
    assert abilities["R"]["parts"][0].time_offset == pytest.approx(3.75)


def test_q_isolation_fails_closed_for_a_multi_target_hit(karthus_data, parse_at):
    _, single = _parse(karthus_data, parse_at, roster_count=1)
    _, multiple = _parse(karthus_data, parse_at, roster_count=2)
    _, explicit_shared = _parse(karthus_data, parse_at, isolated=False)

    assert parts_raw_total(single["Q"]["parts"]) == pytest.approx(372.0)
    assert parts_raw_total(multiple["Q"]["parts"]) == pytest.approx(186.0)
    assert parts_raw_total(explicit_shared["Q"]["parts"]) == pytest.approx(186.0)
    assert "multi-target" in multiple["Q"]["detail"]


def test_wall_reduction_applies_before_every_damage_source(
    karthus_data, parse_at, fight
):
    stats, with_wall = _parse(karthus_data, parse_at, wall=True)
    _, without_wall = _parse(karthus_data, parse_at, wall=False)
    config = {
        "target_magic_resistance": 100,
        "cast_order": get_champion_cast_order("Karthus"),
        "enforce_resource_limits": True,
    }
    reduced = fight(stats, with_wall, **config)
    normal = fight(stats, without_wall, **config)

    assert reduced["effective_mr"] == pytest.approx(75.0)
    assert normal["effective_mr"] == pytest.approx(100.0)
    assert reduced["total_damage"] == pytest.approx(1199.5 / 1.75)
    assert normal["total_damage"] == pytest.approx(1199.5 / 2.0)


def test_defile_tick_count_controls_damage_time_and_mana(karthus_data, parse_at):
    _, zero = _parse(karthus_data, parse_at, ticks=0)
    _, five = _parse(karthus_data, parse_at, ticks=5)
    _, clamped = _parse(karthus_data, parse_at, ticks=999)

    assert zero["E"]["parts"] == ()
    assert zero["E"]["resource_cost"] == 0.0
    assert five["E"]["resource_cost"] == pytest.approx(78.0)
    assert five["E"]["parts"][-1].time_offset == pytest.approx(1.5)
    assert len(clamped["E"]["parts"]) == 40


def test_public_metadata_restricts_karthus_to_the_certified_alive_package():
    meta = get_champion_options_meta("Karthus")

    assert {option["key"] for option in meta["options"]} == {
        "wall_contact",
        "q_isolated",
        "e_ticks",
    }
    assert meta["supported_fight_modes"] == ["one_rotation"]
    assert any("Death Defied" in note for note in meta["assumptions"])
    assert len(meta["sources"]) == 5
