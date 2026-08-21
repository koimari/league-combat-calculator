"""Reviewed crowd control for Vex — and the slots that still withhold.

Doom empowers "her next basic ability", so Q, W and E have no slot-wide
answer and this kit stays coarse.
"""

from src.calculator.champions import vex
from tests import cc_review


class TestReviewedCrowdControl:
    """Vex's crowd-control review, and the slots that still withhold.

    Doom's fear is fight state this module does not price: it empowers
    "her next basic ability" on its own cooldown, and against Looming
    Darkness it replaces E's own slow with a flee.  What keeps Q, E and R
    undeclared is the ledger, not the read — none of their packet rows
    carries a hit time or a single-landing certification.
    """

    def test_the_kit_declares_nothing_because_doom_is_state(self):
        data = cc_review.kit("Vex")
        assert vex.MODULE_CC == {"P": "none", "W": "none"}
        assert vex.parse_abilities.cc_kinds == vex.MODULE_CC
        passive = cc_review.slot_text(data, "P")
        assert "empowers her next basic ability to knock down and fear" in passive
        assert "flee from the epicenter instead" in passive

    def test_looming_darkness_slow_is_the_one_the_flee_overrides(self):
        data = cc_review.kit("Vex")
        assert "slowing them for 2 seconds" in cc_review.slot_text(data, "E")

    def test_shadow_surge_withholds_on_its_two_hit_total_row(self):
        """R is outside Doom's reach and controls nothing, but its packet
        prices the cached Total Magic Damage — the Shadow's hit plus the
        recast dash's arrival — and the cache gives the recast no instant,
        only the window it stays available in."""
        r_text = cc_review.slot_text(cc_review.kit("Vex"), "R")
        assert (
            "shadow stops upon hitting an enemy champion to mark them for "
            "4 seconds, during which they are revealed. shadow surge can "
            "be recast while the target is marked" in r_text
        )
        assert (
            "recast: vex dashes towards the marked target with "
            "displacement immunity. upon arrival, she consumes their mark "
            "and deals magic damage" in r_text
        )

    def test_the_unreviewable_slots_keep_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Vex") == ["E", "Q", "R"]
        coverage = cc_review.fimbulwinter_coverage("Vex")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
