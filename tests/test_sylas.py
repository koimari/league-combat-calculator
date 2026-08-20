"""Sylas's reviewed crowd control (``MODULE_CC``), and the slot that withholds.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import sylas
from tests import cc_review


class TestReviewedCrowdControl:
    """Sylas' whole kit is reviewed once Q's lump declares its own time."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Sylas")
        assert sylas.MODULE_CC == {"W": "none", "E": "immobilize", "Q": "slow"}
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "slowing them for 1.5 seconds" in cc_review.slot_text(data, "Q")
        # Abduct stuns on the chain hit and knocks up on arrival - two
        # immobilize kinds, so the reviewed kind is the un-narrowed one.
        assert "stun them for 0.5 seconds" in cc_review.slot_text(data, "E")
        assert "knocks them up for 0.5 seconds" in cc_review.slot_text(data, "E")

    def test_chain_lash_declares_its_lumped_row_at_the_cast(self):
        """The packet prices the lash and the 0.6s-delayed explosion in one
        part, so the row states when the ledger sees it instead of being
        split into the two cached rows - which re-prices the fight."""
        from src.calculator.champions import parse_champion_abilities
        from src.calculator.stats import calculate_total_stats

        data = cc_review.kit("Sylas")
        parsed = parse_champion_abilities(
            data, 18, 100.0, champion_stats=calculate_total_stats(data, 18, [])
        )
        assert [part.time_offset for part in parsed["Q"]["parts"]] == [0.0]
        assert sylas.SLOTS.packet_spec["slots"]["Q"]["base"] == [
            100.0,
            175.0,
            250.0,
            325.0,
            400.0,
        ]

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Sylas") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Sylas")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
