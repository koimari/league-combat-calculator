"""Reviewed crowd control for Yunara (MODULE_CC).

Arc of Judgment slows in both its base and Transcendent forms;
Cultivation of Spirit only adds on-hit damage.
"""

from src.calculator.champions import yunara
from tests import cc_review


class TestReviewedCrowdControl:
    """Yunara's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Yunara")
        assert yunara.MODULE_CC == {"Q": "none", "W": "slow"}
        assert yunara.parse_abilities.cc_kinds == yunara.MODULE_CC
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        # Both W forms slow, so one slot-wide kind covers r_transcendent.
        w_text = cc_review.slot_text(data, "W")
        assert "slows them by 99% decaying over 1.5 seconds" in w_text
        assert "slows them by 99% decaying over 1 second" in w_text

    def test_the_non_damaging_slots_stay_absent(self):
        """E is a dash, R is the Transcendent State buff shell."""
        assert "E" not in yunara.MODULE_CC and "R" not in yunara.MODULE_CC
        assert (
            cc_review.control_words(cc_review.slot_text(cc_review.kit("Yunara"), "E"))
            == []
        )

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Yunara") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Yunara")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
