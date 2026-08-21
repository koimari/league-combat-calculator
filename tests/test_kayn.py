"""Kayn's reviewed crowd control (``MODULE_CC`` plus W's per-form part).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

import pytest

from src.calculator.champions import kayn, parse_champion_abilities
from src.calculator.champions.engine import CC_PER_PART
from src.calculator.stats import calculate_total_stats
from tests import cc_review


def _w_kinds(form):
    data = cc_review.kit("Kayn")
    parsed = parse_champion_abilities(
        data,
        18,
        100.0,
        champion_stats=calculate_total_stats(data, 18, []),
        champion_options={"form": form},
    )
    return sorted({part.cc_kind for part in parsed["W"]["parts"]})


class TestReviewedCrowdControl:
    """Blade's Reach answers by form, so its kind rides the part."""

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert kayn.MODULE_CC == {"Q": "none", "W": CC_PER_PART, "R": "none"}
        assert kayn.parse_abilities.cc_kinds == kayn.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Kayn")
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []

    @pytest.mark.parametrize(
        "form,kind",
        [("base", "slow"), ("shadow_assassin", "slow"), ("darkin", "knockup")],
    )
    def test_blades_reach_carries_the_forms_own_kind(self, form, kind):
        text = cc_review.slot_text(cc_review.kit("Kayn"), "W")
        assert "slowing them by 90% decaying over 1.5 seconds" in text
        assert "blade's reach knocks up enemies hit for 1 second" in text
        assert _w_kinds(form) == [kind]

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Kayn") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Kayn")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
