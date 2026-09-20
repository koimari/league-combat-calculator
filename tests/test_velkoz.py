"""Reviewed crowd control for Vel'Koz (MODULE_CC).

Q and R slow, E knocks up and stuns, the Void Rift only damages.
"""

from src.calculator.champions import velkoz
from tests import cc_review


class TestReviewedCrowdControl:
    """Vel'Koz's reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Vel'Koz")
        assert velkoz.MODULE_CC == {
            "Q": "slow",
            "W": "none",
            "E": "knockup",
            "R": "slow",
            "P": "none",
        }
        assert "slows them by 70%" in cc_review.slot_text(data, "Q")
        assert "slows them by 20%" in cc_review.slot_text(data, "R")
        # E applies both controls on the one cast; the airborne is the
        # declared kind and the stun rides it.
        e_text = cc_review.slot_text(data, "E")
        assert "knocking them up and stunning them" in e_text
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []

    def test_the_passive_stays_absent_from_the_declaration(self):
        """The Deconstruction consume is not an ability event."""
        assert velkoz.MODULE_CC["P"] == "none"
        assert (
            cc_review.control_words(cc_review.slot_text(cc_review.kit("Vel'Koz"), "P"))
            == []
        )
