"""Sivir's crowd-control review: five slots, not one of them a control.

The roster-wide half of this review lives in ``test_module_cc_census.py``.
Sivir applies no control anywhere, so every slot declares "none" and the timed
fight certifies — even on the two damaging rows the ledger cannot time.
"""

from src.calculator.champions import sivir
from tests import cc_review


class TestReviewedCrowdControl:
    """A control-free kit, on two rows the ledger still cannot time."""

    def test_the_damaging_slots_are_control_free_in_the_cached_text(self):
        data = cc_review.kit("Sivir")
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert sivir.MODULE_CC == {
            "P": "none",
            "E": "none",
            "R": "none",
            "Q": "none",
            "W": "none",
        }

    def test_neither_row_is_a_hit_the_ledger_can_time(self):
        """Boomerang Blade is two passes the module prices at the cast
        boundary ("the exact return cadence is not cached"), and Ricochet's
        packet is one stand-in bounce for a four-second empowered attack
        stream — so neither is one authored hit."""
        data = cc_review.kit("Sivir")
        # The return is timed to an event, not to an instant: the cache
        # says when the blade turns around, never when either pass lands.
        assert (
            "upon reaching maximum range, the crossblade returns to her, "
            "resetting the damage modifier and dealing the same damage to "
            "enemies on its way back" in cc_review.slot_text(data, "Q")
        )
        # Ricochet's bounces ride basic attacks over a 4-second buff.
        assert (
            "sivir empowers her crossblade for the next 4 seconds, gaining "
            "bonus attack speed and causing her basic attacks to bounce to "
            "additional surrounding enemies" in cc_review.slot_text(data, "W")
        )
