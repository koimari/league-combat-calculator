"""Gwen's reviewed crowd control (``MODULE_CC``), and the slot that withholds.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

import pytest

from src.calculator.champions import gwen
from tests import cc_review, row_review


class TestReviewedCrowdControl:
    """Skip 'n Slash controls nothing, Needlework slows, Snip Snip! cuts."""

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert gwen.MODULE_CC == {"E": "none", "Q": "none", "R": "slow"}
        assert gwen.parse_abilities.cc_kinds == gwen.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Gwen")
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert "slows them for 1.5 seconds" in cc_review.slot_text(data, "R")

    def test_every_snip_lands_at_the_instant_the_cache_names(self):
        """The cached notes time each snip of the cast individually."""
        entry = cc_review.kit("Gwen")["abilities"]["Q"][0]
        assert (
            "The first snip happens at 0.13 seconds, the last one at the "
            "end of the cast time." in entry["notes"]
        )
        assert (
            "Bonus snips from Snippy stacks each happen at 0.45, 0.4, 0.35 "
            "and 0.23 seconds into the cast time." in entry["notes"]
        )
        assert entry["castTime"] == "0.5"
        full = row_review.parts("Gwen", "Q", q_snippy_stacks=4)
        # Six snips, each a magic half and a true half at the same instant.
        assert [part.time_offset for part in full] == [
            0.13,
            0.13,
            0.23,
            0.23,
            0.35,
            0.35,
            0.4,
            0.4,
            0.45,
            0.45,
            0.5,
            0.5,
        ]
        assert {part.cc_kind for part in full} == {"none"}
        bare = row_review.parts("Gwen", "Q", q_snippy_stacks=0)
        assert [part.time_offset for part in bare] == [0.13, 0.13, 0.5, 0.5]

    def test_the_per_snip_rows_still_sum_to_the_cached_totals(self):
        plain = row_review.cached_row("Gwen", "Q", "Center Damage per Snip")
        final = row_review.cached_row("Gwen", "Q", "Final Snip Center Damage")
        bare = row_review.priced("Gwen", "Q", q_snippy_stacks=0)
        assert bare == pytest.approx(plain + final)
        assert bare == pytest.approx(
            row_review.cached_row("Gwen", "Q", "Minimum Center Damage")
        )
        assert row_review.priced("Gwen", "Q") == pytest.approx(
            row_review.cached_row("Gwen", "Q", "Maximum Center Damage")
        )

    def test_the_timed_fimbulwinter_fight_is_now_exact(self):
        assert cc_review.unreviewed_ability_slots("Gwen") == []
        coverage = cc_review.fimbulwinter_coverage("Gwen")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


def test_the_packet_states_gwens_typed_snips_and_three_ult_casts():
    """Each snip is a magic half and a true half; R prices every cast."""
    parts = row_review.parts("Gwen", "Q", q_snippy_stacks=4, q_center=True)
    assert {part.damage_type for part in parts} == {"magic", "true"}
    assert "on_hit" in row_review.entry("Gwen", "passive")
    assert len(row_review.parts("Gwen", "R", r_casts=3)) == 3
