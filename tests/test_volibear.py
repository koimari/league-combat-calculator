"""Reviewed crowd control for Volibear (MODULE_CC) — and the two slots
that still withhold.

Thundering Smash stuns and Sky Splitter slows.  Stormbringer's slow rides
an impact a second after the cast and Frenzied Maul's bite is a two-part
row with no timing, so this kit stays coarse.
"""

from src.calculator.champions import parse_champion_abilities, volibear
from tests import cc_review


class TestReviewedCrowdControl:
    """Volibear's reviewed crowd control, and the slots that still withhold.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Volibear")
        assert volibear.MODULE_CC == {"Q": "stun", "E": "slow"}
        assert volibear.parse_abilities.cc_kinds == volibear.MODULE_CC
        assert "stunning them for 1 second" in cc_review.slot_text(data, "Q")
        assert "slows them by 40% for 2 seconds" in cc_review.slot_text(data, "E")

    def test_stormbringer_withholds_on_its_unauthored_impact_delay(self):
        """R's slow is real; the row it would ride is not at the cast."""
        data = cc_review.kit("Volibear")
        assert "R" not in volibear.MODULE_CC
        r_text = cc_review.slot_text(data, "R")
        assert "impacts after 1 second, slowing nearby enemies by 50%" in r_text
        assert "enemies within the epicenter are also dealt physical damage" in r_text

    def test_frenzied_maul_withholds_on_its_two_part_bite(self):
        """W is control-free, but its row cannot certify a single hit."""
        data = cc_review.kit("Volibear")
        assert "W" not in volibear.MODULE_CC
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        parsed = parse_champion_abilities(
            data, 18, 100.0, {"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        base, bonus = parsed["W"]["parts"]
        assert base.time_offset is None and bonus.time_offset is None
        assert parsed["W"].get("event_order_certified") is None

    def test_the_unreviewable_slots_keep_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Volibear") == ["R", "W"]
        coverage = cc_review.fimbulwinter_coverage("Volibear")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
