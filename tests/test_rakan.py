"""Revision-backed tests for Rakan's offensive slot map."""

import pytest

from src.calculator.champions import rakan
from tests import cc_review
from tests.ability_math import parts_raw_total


def test_rakan_rotation_counts_each_enemy_damage_cast_once(rakan_data, parse_at):
    _, abilities = parse_at(
        rakan_data,
        18,
        ap=200,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
    )

    expected = {"Q": 390.0, "W": 430.0, "R": 400.0}
    # E (Battle Dance) is a zero-damage support cast: it exists so the
    # rotation casts it and the scanner prices the ally shield.
    assert set(abilities) == set(expected) | {"E"}
    assert abilities["E"]["total_raw"] == 0.0
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
    assert [event["slot"] for event in result["cast_timeline"]] == ["Q", "W", "E", "R"]
    # 235 across the three damaging casts, plus Battle Dance's own 60.
    assert sum(ability["resource_cost"] for ability in abilities.values()) == 295.0
    assert stats["max_mana"] >= 295.0


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


class TestReviewedCrowdControl:
    """Rakan's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Rakan")
        assert rakan.MODULE_CC == {"Q": "none", "W": "knockup", "R": "charm"}
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        # W's own "immobilizing" wording is about Rakan being knocked down
        # mid-dash, not about control he applies.
        w_text = cc_review.slot_text(data, "W")
        assert "knocks them up for 1 second" in w_text
        assert "rakan will be knocked down by any immobilizing" in w_text
        assert "charms and slows them by 75%" in cc_review.slot_text(data, "R")
        # P (self-shield) and E (ally shield and dash) damage nothing and
        # are not in the slot map at all.
        assert "P" not in rakan.MODULE_CC
        assert "E" not in rakan.MODULE_CC

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Rakan") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Rakan")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
