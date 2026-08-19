"""Tests for the Rumble champion module."""

from src.calculator.champions import rumble
from tests import cc_review


class TestReviewedCrowdControl:
    """Rumble's reviewed crowd control, and the one slot that blocks it.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text —
    and Rumble is the batch's one kit that still cannot answer everywhere.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Rumble")
        assert rumble.MODULE_CC == {"E": "slow", "R": "slow"}
        assert "slowing them for 2 seconds" in cc_review.slot_text(data, "E")
        assert "being slowed by 35%" in cc_review.slot_text(data, "R")
        # W (a shield) and P (the heat system) carry no damage row.
        assert "W" not in rumble.MODULE_CC
        assert "P" not in rumble.MODULE_CC

    def test_q_is_unreviewed_because_its_row_reaches_no_event(self):
        # Flamespitter applies no control — but the packet prices a
        # 3-second flamethrower that ticks "every 0.25 seconds" as one
        # aggregate row, so no event of its own could carry the answer.
        # Declaring it would claim a review the ledger cannot show.
        data = cc_review.kit("Rumble")
        q_text = cc_review.slot_text(data, "Q")
        assert "every 0.25 seconds" in q_text
        assert cc_review.control_words(q_text) == []
        assert "Q" not in rumble.MODULE_CC
        assert cc_review.unreviewed_ability_slots("Rumble") == ["Q"]

    def test_the_timed_fimbulwinter_fight_stays_coarse_on_that_slot(self):
        coverage = cc_review.fimbulwinter_coverage("Rumble")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
