"""Reviewed crowd control for Zaahen (MODULE_CC).

Dreaded Return stuns and pulls; The Darkin Glaive knocks up only on its
recast, so that kind is authored per part.
"""

from src.calculator.champions import parse_champion_abilities, zaahen
from tests import cc_review

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _q_kinds(**options):
    """The kinds The Darkin Glaive's parts carry for one option state."""
    parsed = parse_champion_abilities(
        cc_review.kit("Zaahen"), 18, 100.0, _RANKS, champion_options=options or None
    )
    return sorted({part.cc_kind for part in parsed["Q"]["parts"]})


class TestReviewedCrowdControl:
    """Zaahen's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Zaahen")
        assert zaahen.MODULE_CC == {"W": "stun", "E": "none", "R": "none"}
        assert zaahen.parse_abilities.cc_kinds == zaahen.MODULE_CC
        w_text = cc_review.slot_text(data, "W")
        assert "stunned for 0.25 seconds, and pulled 225 units" in w_text
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        # R's only control word is the immunity Zaahen gains himself.
        r_text = cc_review.slot_text(data, "R")
        assert "gains crowd control immunity over the cast time" in r_text

    def test_grim_deliverance_damage_rides_the_slam(self):
        assert zaahen._R_SLAM_DELAY_SECONDS == 0.6
        assert "slams his glaive down after a 0.6-second delay" in (
            cc_review.slot_text(cc_review.kit("Zaahen"), "R")
        )

    def test_the_darkin_glaive_carries_the_variant_it_prices(self):
        """Only the recast row knocks up."""
        data = cc_review.kit("Zaahen")
        assert "Q" not in zaahen.MODULE_CC
        assert "knock up the target for 0.75 seconds" in cc_review.slot_text(data, "Q")
        assert _q_kinds() == ["none"]
        assert _q_kinds(q_variant=1) == ["none"]
        assert _q_kinds(q_variant=2) == ["knockup"]

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Zaahen") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Zaahen")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
