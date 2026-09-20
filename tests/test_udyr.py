"""Udyr's reviewed crowd control (``MODULE_CC``).

The roster-wide half of this review lives in ``test_module_cc_census.py``.
"""

from src.calculator.champions import get_champion_module_contract, udyr
from tests import cc_review


class TestReviewedCrowdControl:
    """Wingborne Storm's blizzard is the kit's only cast-damage row."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Udyr")
        # A cc-only slot states its kind in MODULE_CC like any other and
        # publishes the sourced interval as a ControlEvent (CF8).
        assert udyr.MODULE_CC == {
            "E": "stun",
            "R": "slow",
            "P": "none",
            "Q": "none",
            "W": "none",
        }
        assert "slows them while they remain within" in cc_review.slot_text(data, "R")
        # Blazing Stampede is where the kit's stun lives, and it deals no
        # damage of its own, so no part can carry that answer: the stun is
        # published as a standalone sourced ControlEvent instead (the
        # Rammus-E shape), which is what lets E be no_damage — nothing
        # damage-relevant is left unmodeled — rather than out_of_scope.
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == ["stun"]
        assert get_champion_module_contract("Udyr").coverage["E"] == "no_damage"
