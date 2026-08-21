"""Tests for the Rell champion module."""

from src.calculator.champions import rell
from tests import cc_review


class TestReviewedCrowdControl:
    """Rell's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Rell")
        assert rell.MODULE_CC == {
            "Q": "stun",
            "W": "immobilize",
            "E": "none",
            "R": "pull",
        }
        q_text = cc_review.slot_text(data, "Q")
        assert "dealing them magic damage and stunning them for 0.65 seconds" in q_text
        # Both W forms apply two immobilize kinds at once.
        w_text = cc_review.slot_text(data, "W")
        assert "stuns them for 0.8 seconds, and knocks them up" in w_text
        assert "stuns the target for 0.6 seconds, and flings them 150 units" in w_text
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        assert "drags them towards her" in cc_review.slot_text(data, "R")
        # P is an on-hit rider on the auto stream.
        assert "P" not in rell.MODULE_CC

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Rell") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Rell")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


def test_the_published_options_are_the_one_the_module_reads():
    """Rell's only choice is which W she casts."""
    from src.calculator.champions import get_champion_options_meta

    keys = {option["key"] for option in get_champion_options_meta("Rell")["options"]}
    assert keys == {"w_variant"}
