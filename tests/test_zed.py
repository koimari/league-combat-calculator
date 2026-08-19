"""Reviewed crowd control for Zed (MODULE_CC).

Nothing Zed himself casts controls: Shadow Slash's slow belongs to a
Shadow's copy of it, which this module does not price.
"""

from src.calculator.champions import zed
from tests import cc_review


class TestReviewedCrowdControl:
    """Zed's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Zed")
        assert zed.MODULE_CC == {"Q": "none", "E": "none", "R": "none"}
        assert zed.parse_abilities.cc_kinds == zed.MODULE_CC
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []

    def test_shadow_slash_slows_only_from_a_shadows_copy(self):
        data = cc_review.kit("Zed")
        e_text = cc_review.slot_text(data, "E")
        assert "zed slashes to deal physical damage to nearby enemies" in e_text
        assert "enemies hit by a shadow's slash are slowed for 1.5 seconds" in e_text
        assert cc_review.control_words(e_text) == ["slow"]

    def test_the_no_damage_slots_stay_absent(self):
        assert "P" not in zed.MODULE_CC and "W" not in zed.MODULE_CC
        assert zed.MODULE_COVERAGE["P"] == "no_damage"
        assert zed.MODULE_COVERAGE["W"] == "no_damage"

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Zed") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Zed")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
