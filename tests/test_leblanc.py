"""LeBlanc's reviewed crowd control (``MODULE_CC`` plus Mimic's own part).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

import pytest

from src.calculator.champions import leblanc, parse_champion_abilities
from src.calculator.stats import calculate_total_stats
from tests import cc_review


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
        assert leblanc.MODULE_CC == {"W": "none"}
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

    def test_the_unreviewable_slots_keep_the_fight_coarse(self):
        data = cc_review.kit("LeBlanc")
        assert "root them for 1.5 seconds" in cc_review.slot_text(data, "E")
        assert cc_review.unreviewed_ability_slots("LeBlanc") == ["E", "Q"]
        coverage = cc_review.fimbulwinter_coverage("LeBlanc")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
