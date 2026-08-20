"""Kennen's crowd-control review: every slot withholds, and none for timing.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.  Kennen has
no ``MODULE_CC`` because Mark of the Storm puts the stun on the target's
stack count rather than on any one ability — the third application stuns,
the first two do not, and every slot is capable of being either.
"""

from src.calculator.champions import kennen
from tests import cc_review, row_review


class TestReviewedCrowdControl:
    """Why Kennen withholds: the stun belongs to the mark, not the slot."""

    def test_the_kit_declares_nothing_because_the_mark_is_state(self):
        passive = cc_review.slot_text(cc_review.kit("Kennen"), "P")
        assert not hasattr(kennen, "MODULE_CC")
        assert (
            "kennen's abilities apply a stack of mark of the storm to "
            "enemies hit for 6 seconds, refreshing on subsequent "
            "applications and stacking up to 3 times" in passive
        )
        assert (
            "the third stack against a target consumes them all to stun "
            "them for 1.25 seconds" in passive
        )

    def test_no_damaging_slot_states_a_control_of_its_own(self):
        """Q, W and E only damage; the storm's own entry never says stun."""
        data = cc_review.kit("Kennen")
        for slot in ("Q", "W", "E", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == [], slot

    def test_the_storm_already_strikes_on_its_sourced_cadence(self):
        """R's blocker is the kind alone: its bolts are authored hits.

        "Kennen summons a storm around himself for 3 seconds" and "the
        storm strikes lightning bolts down on nearby enemies every 0.5
        seconds" — six bolts on a half-second beat, which the module
        authors, so R reaches the event ledger and still cannot say what
        the bolt that lands the third mark did.
        """
        r_text = cc_review.slot_text(cc_review.kit("Kennen"), "R")
        assert "kennen summons a storm around himself for 3 seconds" in r_text
        assert (
            "the storm strikes lightning bolts down on nearby enemies "
            "every 0.5 seconds" in r_text
        )
        (bolts,) = row_review.parts("Kennen", "R")
        assert (bolts.time_offset, bolts.hit_interval, bolts.count) == (0.5, 0.5, 6)
        assert bolts.cc_kind is None

    def test_the_unreviewable_slots_keep_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Kennen") == ["E", "Q", "R", "W"]
        coverage = cc_review.fimbulwinter_coverage("Kennen")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]


def test_the_storm_authors_a_certified_order():
    """R's bolts ride the ordered schedule the cadence test pins."""
    assert row_review.entry("Kennen", "R", r_bolts=6)["event_order_certified"]
