"""Reviewed crowd control for Zoe (MODULE_CC) — and the slot that still
withholds.

Sleepy Trouble Bubble puts its target to sleep; Paddle Star! only
explodes.  Spell Thief's three bolts are one aggregated row with no
cadence, so this kit stays coarse.
"""

from src.calculator.champions import parse_champion_abilities, zoe
from tests import cc_review


class TestReviewedCrowdControl:
    """Zoe's reviewed crowd control, and the slot that still withholds.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Zoe")
        assert zoe.MODULE_CC == {"Q": "none", "E": "sleep"}
        assert zoe.parse_abilities.cc_kinds == zoe.MODULE_CC
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        # The drowsy is the ramp; the sleep is what the cast lands.
        e_text = cc_review.slot_text(data, "E")
        assert "inflicts them with drowsy for 1.4 seconds" in e_text
        assert "until they fall asleep for 2.25 seconds" in e_text

    def test_spell_thief_withholds_on_its_aggregated_bolt_row(self):
        """W is control-free, but its three bolts have no cadence."""
        data = cc_review.kit("Zoe")
        assert "W" not in zoe.MODULE_CC
        assert "she shoots one bolt at a time" in cc_review.slot_text(data, "W")
        parsed = parse_champion_abilities(
            data, 18, 100.0, {"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        (part,) = parsed["W"]["parts"]
        assert part.count == zoe._W_BOLTS
        assert part.time_offset is None
        assert part.hit_interval is None

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Zoe") == ["W"]
        coverage = cc_review.fimbulwinter_coverage("Zoe")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
