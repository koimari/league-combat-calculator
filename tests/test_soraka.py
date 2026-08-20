"""Revision-backed tests for Soraka's offensive slot map."""

import pytest

from tests.ability_math import parts_raw_total
from src.calculator.champions import soraka
from tests import cc_review


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


class TestReviewedCrowdControl:
    """Soraka's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Soraka")
        assert soraka.MODULE_CC == {"Q": "slow", "E": "root"}
        assert "slowing them by 30% for 1.5 seconds" in cc_review.slot_text(data, "Q")
        # Equinox silences while the zone stands and roots when it erupts;
        # the root is the immobilizing half its two hits apply.
        assert "silences enemies within" in cc_review.slot_text(data, "E")
        assert "root them for a duration" in cc_review.slot_text(data, "E")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Soraka") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Soraka")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
