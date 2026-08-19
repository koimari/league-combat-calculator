"""Reviewed crowd control for Leona (MODULE_CC) — and the slot that still
withholds.

Eclipse detonates 3 seconds after its cast and controls nothing; Zenith
Blade roots; Solar Flare strikes 0.625 seconds after its cast and slows
every enemy it hits.  Shield of Daybreak's stun is real but its row
authors no part, so this kit stays coarse.
"""

from src.calculator.champions import leona, parse_champion_abilities
from tests import cc_review

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


class TestReviewedCrowdControl:
    """Leona's reviewed crowd control, and the delays that carry it.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Leona")
        assert leona.MODULE_CC == {"W": "none", "E": "root", "R": "slow"}
        assert leona.parse_abilities.cc_kinds == leona.MODULE_CC
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "roots them for 0.5 seconds" in cc_review.slot_text(data, "E")
        assert "slowed by 80% for 1.75 seconds" in cc_review.slot_text(data, "R")

    def test_the_epicenter_stun_is_the_conditional_the_slow_is_not(self):
        """R's slow lands on every enemy hit; the stun needs the epicenter."""
        text = cc_review.slot_text(cc_review.kit("Leona"), "R")
        assert "also stunned for the same duration if they are struck by the" in text

    def test_eclipse_detonates_at_the_end_of_its_sourced_guard(self):
        data = cc_review.kit("Leona")
        w_text = cc_review.slot_text(data, "W")
        assert "raises her guard for 3 seconds" in w_text
        assert "her shield detonates after the duration, dealing magic damage" in w_text
        (part,) = parse_champion_abilities(data, 18, 100.0, _RANKS)["W"]["parts"]
        assert part.time_offset == 3.0
        assert part.cc_kind == "none"

    def test_solar_flare_strikes_on_its_sourced_delay(self):
        data = cc_review.kit("Leona")
        assert "strikes upon the target location after 0.625 seconds" in (
            cc_review.slot_text(data, "R")
        )
        (part,) = parse_champion_abilities(data, 18, 100.0, _RANKS)["R"]["parts"]
        assert part.time_offset == 0.625
        assert part.cc_kind == "slow"

    def test_shield_of_daybreak_withholds_on_its_partless_row(self):
        """Q's stun is real; its row is an on-hit payload, not a hit."""
        data = cc_review.kit("Leona")
        assert "Q" not in leona.MODULE_CC
        assert "stun the target for 1 second" in cc_review.slot_text(data, "Q")
        entry = parse_champion_abilities(data, 18, 100.0, _RANKS)["Q"]
        assert entry["parts"] == ()
        assert entry["on_hit"]["name"] == "Shield of Daybreak"

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Leona") == ["Q"]
        coverage = cc_review.fimbulwinter_coverage("Leona")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
