"""Kled's reviewed crowd control (``MODULE_CC``), and the slots that withhold.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

import pytest

from src.calculator.champions import kled
from tests import cc_review, row_review


class TestReviewedCrowdControl:
    """Chaaaaaaaarge!!! knocks back, Bear Trap pulls at its tether's end."""

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert kled.MODULE_CC == {"W": "none", "R": "knockback"}
        assert kled.parse_abilities.cc_kinds == kled.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Kled")
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "knock them back 150 units" in cc_review.slot_text(data, "R")

    def test_the_trap_and_its_pull_are_two_hits_the_cache_times(self):
        """Q is not in MODULE_CC because its two hits answer differently:
        the thrown trap only reveals and tethers, and the pull 1.75
        seconds later is the immobilize."""
        q_text = cc_review.slot_text(cc_review.kit("Kled"), "Q")
        assert "forming a tether between kled and the target for 1.75 seconds" in q_text
        assert (
            "if it is not broken before then, kled pulls the target 150 "
            "units toward him, deals physical damage and slows them for "
            "2.5 seconds" in q_text
        )
        assert "Q" not in kled.MODULE_CC
        trap, pull = row_review.parts("Kled", "Q")
        assert (trap.time_offset, trap.cc_kind) == (0.0, "none")
        assert (pull.time_offset, pull.cc_kind) == (1.75, "pull")
        # The two cached rows still add up to the cached Total row.
        assert trap.amount + pull.amount == pytest.approx(
            row_review.cached_row("Kled", "Q", "Total Physical Damage")
        )
        assert trap.amount == pytest.approx(
            row_review.cached_row("Kled", "Q", "Physical Damage")
        )
        # A tether the target breaks prices the trap hit alone.
        (only_trap,) = row_review.parts("Kled", "Q", q_pull=False)
        assert (only_trap.time_offset, only_trap.cc_kind) == (0.0, "none")

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        """Jousting's row is the first dash plus the recast dash, and the
        cache times the recast only relative to an unstated dash end."""
        e_text = cc_review.slot_text(cc_review.kit("Kled"), "E")
        assert (
            "jousting can be recast after 0.5 seconds of the first dash "
            "ending while the target is marked" in e_text
        )
        assert "E" not in kled.MODULE_CC
        assert cc_review.unreviewed_ability_slots("Kled") == ["E"]
        coverage = cc_review.fimbulwinter_coverage("Kled")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
