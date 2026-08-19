"""Swain's reviewed crowd control (``MODULE_CC`` plus R's per-variant part).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import swain
from tests import cc_review


def _r_parts(variant: int):
    """Ravenous Flock's ultimate parts for one variant, through the module."""
    data = cc_review.kit("Swain")
    results = swain.parse_abilities(
        data, 18, 0.0, champion_options={"r_variant": variant}
    )
    return results["R"]["parts"]


class TestReviewedCrowdControl:
    """Swain's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Swain")
        assert swain.MODULE_CC == {"Q": "none", "W": "slow", "E": "root"}
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert "slowing them by 50% for 1.5 seconds" in cc_review.slot_text(data, "W")
        # E's pull and knock-back ride the recast; the detonation that this
        # row prices roots.
        assert "rooting them for 1.5 seconds" in cc_review.slot_text(data, "E")

    def test_r_answers_by_variant_because_the_two_casts_differ(self):
        """Demonic Ascension drains without control; Demonflare slows, so R
        authors its kind on the selected variant's part."""
        assert "slows them by 50%" in cc_review.slot_text(cc_review.kit("Swain"), "R")
        assert "R" not in swain.MODULE_CC
        assert _r_parts(0)[0].cc_kind == "none"
        assert _r_parts(1)[0].cc_kind == "slow"

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Swain") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Swain")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
