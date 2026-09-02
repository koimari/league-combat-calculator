"""Reviewed crowd control for Zoe (MODULE_CC), total over her five slots.

Sleepy Trouble Bubble puts its target to sleep; Paddle Star! only
explodes.  Spell Thief's three bolts are one aggregated row with no
cadence, so its reviewed "none" lands on a part nothing reads.
"""

from src.calculator.champions import parse_champion_abilities, zoe
from tests import cc_review


class TestReviewedCrowdControl:
    """Zoe's reviewed crowd control, on every slot her module emits.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
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
        assert zoe.parse_abilities.cc_kinds == zoe.MODULE_CC
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

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        assert cc_review.unreviewed_ability_slots("Zoe") == []
        coverage = cc_review.fimbulwinter_coverage("Zoe")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
