"""Tests for the Ryze champion module."""

from src.calculator.champions import ryze
from tests import cc_review


class TestReviewedCrowdControl:
    """Ryze's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Ryze")
        assert ryze.MODULE_CC == {"Q": "none", "W": "slow", "E": "none", "R": "none"}
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        # W's Flux bonus roots instead of slowing, but that empowerment has
        # no option or damage row here, so the priced cast is the base
        # seize and the slow is what it applies.
        w_text = cc_review.slot_text(data, "W")
        assert "dealing magic damage and slowing them by 50%" in w_text
        assert "the target is rooted instead of slowed" in w_text
        # R's root, disarm and silence land on Ryze and his own allies.
        r_text = cc_review.slot_text(data, "R")
        assert "ryze and all allied units within the portal will blink" in r_text
        assert "become rooted, disarmed, silenced and untargetable" in r_text
        # P only raises Ryze's maximum mana.
        assert "P" not in ryze.MODULE_CC

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Ryze") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Ryze")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
