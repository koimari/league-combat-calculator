"""LeBlanc's reviewed crowd control (``MODULE_CC`` plus Mimic's own part).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

import pytest

from src.calculator.champions import leblanc, parse_champion_abilities
from src.calculator.champions.engine import CC_PER_PART
from src.calculator.stats import calculate_total_stats
from tests import cc_review, row_review


def _r_kinds(variant):
    data = cc_review.kit("LeBlanc")
    parsed = parse_champion_abilities(
        data,
        18,
        100.0,
        champion_stats=calculate_total_stats(data, 18, []),
        champion_options={"r_mimic": variant},
    )
    return [part.cc_kind for part in parsed["R"]["parts"]]


class TestReviewedCrowdControl:
    """Mimic answers as the ability it copies, so its kind rides the part."""

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert leblanc.MODULE_CC == {"W": "none", "E": CC_PER_PART, "R": CC_PER_PART}
        assert leblanc.parse_abilities.cc_kinds == leblanc.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("LeBlanc")
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []

    @pytest.mark.parametrize("variant,kinds", [("Q", ["none"]), ("W", ["none"])])
    def test_mimic_carries_the_copied_abilitys_answer(self, variant, kinds):
        assert _r_kinds(variant) == kinds

    def test_mimicking_ethereal_chains_is_left_unreviewed(self):
        """That variant prices the application and the fracture together
        and only the fracture roots, so no one kind is true of the row."""
        assert _r_kinds("E") == [None]

    def test_the_chain_and_its_fracture_are_two_hits_the_cache_times(self):
        """E is not in MODULE_CC because its two hits answer differently:
        the chain's application only tethers, and the fracture 1.5 seconds
        later is the root."""
        e_text = cc_review.slot_text(cc_review.kit("LeBlanc"), "E")
        assert "forms a tether between leblanc and the target for 1.5 seconds" in e_text
        assert (
            "if the tether is not broken by the end of its duration, it "
            "fractures to deal magic damage to the target and root them "
            "for 1.5 seconds" in e_text
        )
        assert leblanc.MODULE_CC["E"] == CC_PER_PART
        chain, fracture = row_review.parts("LeBlanc", "E")
        assert (chain.time_offset, chain.cc_kind) == (0.0, "none")
        assert (fracture.time_offset, fracture.cc_kind) == (1.5, "root")
        assert chain.amount == pytest.approx(
            row_review.cached_row("LeBlanc", "E", "Magic Damage")
        )
        assert fracture.amount == pytest.approx(
            row_review.cached_row("LeBlanc", "E", "Fracture Magic Damage")
        )
        assert row_review.priced("LeBlanc", "E") == pytest.approx(
            row_review.cached_row("LeBlanc", "E", "Total Damage")
        )
        # A tether the target breaks prices the application alone.
        (only_chain,) = row_review.parts("LeBlanc", "E", e_chain_complete=False)
        assert (only_chain.time_offset, only_chain.cc_kind) == (0.0, "none")

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        """Sigil of Malice's row is the orb plus the mark's consumption,
        and the cache times that second hit to another cast it does not
        name — a 3.5-second window, not a cadence."""
        q_text = cc_review.slot_text(cc_review.kit("LeBlanc"), "Q")
        assert (
            "leblanc's next damaging ability against the marked target "
            "will consume the mark to deal the same magic damage again" in q_text
        )
        assert "Q" not in leblanc.MODULE_CC
        assert cc_review.unreviewed_ability_slots("LeBlanc") == ["Q"]
        coverage = cc_review.fimbulwinter_coverage("LeBlanc")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]


def test_a_consumed_mark_leaves_one_q_row():
    """Q's mark detonation is the same row, not a second one."""
    assert len(row_review.parts("LeBlanc", "Q", q_consume=True, r_mimic="Q")) == 1
