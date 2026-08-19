"""Reviewed crowd control for Xin Zhao (MODULE_CC) — and the slot that
still withholds.

Wind Becomes Lightning and Audacious Charge slow; Crescent Guard displaces
only unChallenged targets, which the duel target never is.  Q prices one
of three empowered attacks, so it carries no slot-wide answer and this kit
stays coarse.
"""

import pytest

from src.calculator.champions import xin_zhao
from tests import cc_review, row_review


class TestReviewedCrowdControl:
    """Xin Zhao's reviewed crowd control, and the slots that still withhold.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Xin Zhao")
        assert xin_zhao.MODULE_CC == {"W": "slow", "E": "slow", "R": "none"}
        assert xin_zhao.parse_abilities.cc_kinds == xin_zhao.MODULE_CC
        assert "slowing all targets hit by 30%" in cc_review.slot_text(data, "E")
        # W's slow is the thrust's, and the module now prices the whole
        # cast — the four slashes plus that thrust.
        assert "slowing them by 50%" in cc_review.slot_text(data, "W")
        assert xin_zhao.PACKET_SPEC["slots"]["W"]["base"] == [
            7.5,
            10.0,
            12.5,
            15.0,
            17.5,
        ]

    def test_crescent_guard_never_displaces_a_challenged_duel_target(self):
        data = cc_review.kit("Xin Zhao")
        r_text = cc_review.slot_text(data, "R")
        assert "knocking back all targets hit that are not challenged" in r_text
        assert "basic attacks and audacious charge apply the challenged mark" in r_text

    def test_three_talon_strike_has_no_slot_wide_answer(self):
        """Only the third of Q's three empowered attacks knocks up."""
        data = cc_review.kit("Xin Zhao")
        assert "Q" not in xin_zhao.MODULE_CC
        assert "the third attack knocks up the target" in cc_review.slot_text(data, "Q")
        # The row covers all three empowered attacks, but only one of them
        # knocks up, so no slot-wide kind answers for it.
        assert xin_zhao.PACKET_SPEC["slots"]["Q"]["base"] == [
            15.0,
            30.0,
            45.0,
            60.0,
            75.0,
        ]

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Xin Zhao") == ["Q"]
        coverage = cc_review.fimbulwinter_coverage("Xin Zhao")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]


class TestPricedRows:
    """Q and W price the cast's own total, not one instance of it.

    The generated packet picked "Bonus Physical Damage" for Q (one of the
    three empowered attacks) and "Physical Damage per Slash" for W (one
    slash of four, and no thrust).  Both cached entries also carry the
    total the wiki computes for the whole cast, and that is what the
    module reads.
    """

    def test_three_talon_strike_prices_all_three_empowered_attacks(self):
        total = row_review.cached_row("Xin Zhao", "Q", "Total Bonus Physical Damage")
        one = row_review.cached_row("Xin Zhao", "Q", "Bonus Physical Damage")
        assert total == pytest.approx(3 * one)
        assert row_review.priced("Xin Zhao", "Q") == pytest.approx(total)
        assert row_review.packet_row("Xin Zhao", "Q", xin_zhao)[4] == 75.0

    def test_wind_becomes_lightning_prices_the_slashes_and_the_thrust(self):
        total = row_review.cached_row("Xin Zhao", "W", "Total Physical Damage")
        slashes = row_review.cached_row("Xin Zhao", "W", "Slash Total Physical Damage")
        thrust = row_review.cached_row("Xin Zhao", "W", "Thrust Physical Damage")
        per_slash = row_review.cached_row("Xin Zhao", "W", "Physical Damage per Slash")
        assert total == pytest.approx(slashes + thrust)
        assert slashes == pytest.approx(4 * per_slash)
        assert row_review.priced("Xin Zhao", "W") == pytest.approx(total)
        assert row_review.packet_row("Xin Zhao", "W", xin_zhao)[4] == 17.5
