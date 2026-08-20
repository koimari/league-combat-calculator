"""Mel's reviewed crowd control (``MODULE_CC`` plus Solar Snare's two parts).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import mel, parse_champion_abilities
from src.calculator.stats import calculate_total_stats
from tests import cc_review


class TestReviewedCrowdControl:
    """Solar Snare's orb roots and its field slows, so E answers per part."""

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert mel.MODULE_CC == {"Q": "none", "R": "none"}
        assert mel.parse_abilities.cc_kinds == mel.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Mel")
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []

    def test_solar_snares_orb_and_field_carry_their_own_kinds(self):
        text = cc_review.slot_text(cc_review.kit("Mel"), "E")
        assert "rooted for 1.5 seconds" in text
        assert "slowed by 30% every 0.125 seconds" in text
        data = cc_review.kit("Mel")
        parsed = parse_champion_abilities(
            data, 18, 100.0, champion_stats=calculate_total_stats(data, 18, [])
        )
        assert [part.cc_kind for part in parsed["E"]["parts"]] == ["root", "slow"]

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Mel") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Mel")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
