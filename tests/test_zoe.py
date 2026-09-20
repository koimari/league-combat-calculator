"""Reviewed crowd control for Zoe (MODULE_CC), total over her five slots.

Sleepy Trouble Bubble puts its target to sleep; Paddle Star! only
explodes.  Spell Thief's three bolts are one aggregated row with no
cadence, so its reviewed "none" lands on a part nothing reads.
"""

from src.calculator.champions import parse_champion_abilities, zoe
from tests import cc_review


class TestReviewedCrowdControl:
    """Zoe's reviewed crowd control, on every slot her module emits.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Zoe")
        assert zoe.MODULE_CC == {
            "Q": "none",
            "E": "sleep",
            "P": "none",
            "W": "none",
            "R": "none",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        # The drowsy is the ramp; the sleep is what the cast lands.
        e_text = cc_review.slot_text(data, "E")
        assert "inflicts them with drowsy for 1.4 seconds" in e_text
        assert "until they fall asleep for 2.25 seconds" in e_text

    def test_spell_thiefs_aggregated_bolt_row_has_no_cadence(self):
        """W is control-free, and its three bolts land on no stated instant."""
        data = cc_review.kit("Zoe")
        assert zoe.MODULE_CC["W"] == "none"
        assert "she shoots one bolt at a time" in cc_review.slot_text(data, "W")
        parsed = parse_champion_abilities(
            data, 18, 100.0, {"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        (part,) = parsed["W"]["parts"]
        assert part.count == zoe._W_BOLTS
        assert part.time_offset is None
        assert part.hit_interval is None
