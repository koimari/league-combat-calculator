"""Reviewed crowd control for Vel'Koz (MODULE_CC).

Q and R slow, E knocks up and stuns, the Void Rift only damages.
"""

from src.calculator.champions import velkoz
from tests import cc_review


class TestReviewedCrowdControl:
    """Vel'Koz's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Vel'Koz")
        assert velkoz.MODULE_CC == {
            "Q": "slow",
            "W": "none",
            "E": "knockup",
            "R": "slow",
        }
        assert velkoz.parse_abilities.cc_kinds == velkoz.MODULE_CC
        assert "slows them by 70%" in cc_review.slot_text(data, "Q")
        assert "slows them by 20%" in cc_review.slot_text(data, "R")
        # E applies both controls on the one cast; the airborne is the
        # declared kind and the stun rides it.
        e_text = cc_review.slot_text(data, "E")
        assert "knocking them up and stunning them" in e_text
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []

    def test_the_passive_stays_absent_from_the_declaration(self):
        """The Deconstruction consume is not an ability event."""
        assert "P" not in velkoz.MODULE_CC
        assert (
            cc_review.control_words(cc_review.slot_text(cc_review.kit("Vel'Koz"), "P"))
            == []
        )

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Vel'Koz") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Vel'Koz")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
