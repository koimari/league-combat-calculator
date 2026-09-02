"""Tests for the Rek'Sai champion module."""

import pytest

from src.calculator.champions import reksai
from tests import cc_review, row_review


class TestReviewedCrowdControl:
    """Rek'Sai's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Rek'Sai")
        assert reksai.MODULE_CC == {
            "Q": "none",
            "W": "knockup",
            "E": "none",
            "R": "none",
            "P": "none",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert "knock them up for 1 second" in cc_review.slot_text(data, "W")
        # E's only control word is about Rek'Sai being unable to enter a
        # tunnel while immobilized, not about control she applies.
        e_text = cc_review.slot_text(data, "E")
        assert "bites the target enemy, dealing physical damage" in e_text
        assert "cannot enter a tunnel while immobilized" in e_text
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []
        # P is Fury generation and healing, with no damage row.
        assert reksai.MODULE_CC["P"] == "none"

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Rek'Sai") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Rek'Sai")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestPricedRows:
    """Queen's Wrath prices all three empowered attacks.

    The generated packet read "Bonus Physical Damage", one of the three
    the cast empowers ("for up to 3 total empowered attacks"); the
    cache's "Total Bonus Physical Damage" row is all three.
    """

    def test_queens_wrath_prices_all_three_empowered_attacks(self):
        total = row_review.cached_row("Rek'Sai", "Q", "Total Bonus Physical Damage")
        one = row_review.cached_row("Rek'Sai", "Q", "Bonus Physical Damage")
        assert total == pytest.approx(3 * one)
        assert row_review.priced("Rek'Sai", "Q", q_variant=0) == pytest.approx(total)
        assert row_review.packet_row("Rek'Sai", "Q", reksai, variant=0)[4] == 0.0

    def test_prey_seeker_is_untouched(self):
        """Variant 1 is one bolt and keeps the packet's own row."""
        magic = row_review.cached_row("Rek'Sai", "Q", "Magic Damage", entry=1)
        assert row_review.priced("Rek'Sai", "Q", q_variant=1) == pytest.approx(magic)


def test_the_published_options_are_the_three_the_module_reads():
    """Q variant, the Fury Furious Bite reads, and the Fury the burrow spends."""
    from src.calculator.champions import get_champion_options_meta

    keys = {option["key"] for option in get_champion_options_meta("Rek'Sai")["options"]}
    assert keys == {"q_variant", "e_fury", "p_burrow_fury"}
