"""Reviewed crowd control for Vladimir (MODULE_CC) — and the slot that
still withholds.

Sanguine Pool and a fully charged Tides of Blood slow; Transfusion does
not.  Hemoplague's burst lands 4 seconds after its cast, and the packet
does not author that, so this kit stays coarse.
"""

from src.calculator.champions import vladimir
from tests import cc_review


class TestReviewedCrowdControl:
    """Vladimir's reviewed crowd control, and the slot that still withholds.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Vladimir")
        assert vladimir.MODULE_CC == {"Q": "none", "W": "slow", "E": "slow"}
        assert vladimir.parse_abilities.cc_kinds == vladimir.MODULE_CC
        # Q's only control words describe Vladimir's own Crimson Rush:
        # it "depletes 75% slower during Sanguine Pool, Tides of Blood, or
        # stasis" — a condition on him, never applied to the target.
        q_text = cc_review.slot_text(data, "Q")
        assert cc_review.control_words(q_text) == ["slow", "stasis"]
        assert "crimson rush depletes 75% slower during" in q_text
        assert "are slowed by 40%" in cc_review.slot_text(data, "W")
        # E prices the fully charged nova, which is exactly the branch the
        # cached text puts the slow on.
        e_text = cc_review.slot_text(data, "E")
        assert "charged for at least 1 second, enemies hit are also slowed" in e_text
        assert vladimir.PACKET_SPEC["slots"]["E"]["base"] == [
            60.0,
            90.0,
            120.0,
            150.0,
            180.0,
        ]

    def test_hemoplague_withholds_on_its_unauthored_infection_delay(self):
        """R controls nothing, but its burst does not land at the cast."""
        data = cc_review.kit("Vladimir")
        assert "R" not in vladimir.MODULE_CC
        r_text = cc_review.slot_text(data, "R")
        assert cc_review.control_words(r_text) == []
        assert "infects enemies hit for 4 seconds" in r_text
        assert "after the duration, the infection bursts" in r_text

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Vladimir") == ["R"]
        coverage = cc_review.fimbulwinter_coverage("Vladimir")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
