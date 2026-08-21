"""Reviewed crowd control for Master Yi (MODULE_CC) — and the slot that
still withholds.

Alpha Strike controls nothing and lands after Master Yi reappears, 1.087
seconds after the cast starts.  Wuju Style's row prices an on-hit rider
as one direct hit, so it has no instant a marker could ride.
"""

from src.calculator.champions import master_yi, parse_champion_abilities
from tests import cc_review

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


class TestReviewedCrowdControl:
    """Master Yi's reviewed crowd control, and the delay that carries Q.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Master Yi")
        assert master_yi.MODULE_CC == {"Q": "none"}
        assert master_yi.parse_abilities.cc_kinds == master_yi.MODULE_CC
        # Alpha Strike's only "unable to act" clause is about Master Yi.
        q_text = cc_review.slot_text(data, "Q")
        assert "master yi vanishes and becomes unable to act" in q_text
        assert cc_review.control_words(q_text) == []

    def test_alpha_strike_lands_when_master_yi_reappears(self):
        data = cc_review.kit("Master Yi")
        entry = data["abilities"]["Q"][0]
        assert "1.087 seconds total after the start of the cast" in (
            entry["effects"][1]["description"]
        )
        assert "Alpha Strike's primary damage applies after Master Yi reappears" in (
            entry["notes"]
        )
        (part,) = parse_champion_abilities(data, 18, 100.0, _RANKS)["Q"]["parts"]
        assert part.time_offset == 1.087
        assert part.cc_kind == "none"

    def test_wuju_style_withholds_because_its_row_is_an_on_hit_rider(self):
        """E's packet prices one direct hit for a 5-second attack buff."""
        data = cc_review.kit("Master Yi")
        assert "E" not in master_yi.MODULE_CC
        assert "empowers his basic attacks within the next 5 seconds" in (
            cc_review.slot_text(data, "E")
        )
        entry = parse_champion_abilities(data, 18, 100.0, _RANKS)["E"]
        (part,) = entry["parts"]
        assert part.time_offset is None
        assert entry.get("event_order_certified") is None

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Master Yi") == ["E"]
        coverage = cc_review.fimbulwinter_coverage("Master Yi")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
