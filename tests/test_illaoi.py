"""Reviewed crowd control for Illaoi (MODULE_CC, wave 4B).

Illaoi's control is E's tether severance, which damages nothing.
"""

from tests import cc_review

# ---------------------------------------------------------------------------
# Reviewed crowd control (MODULE_CC, wave 4B)
# ---------------------------------------------------------------------------

_CC_CHAMPION = "Illaoi"
_CC_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_CC = cc_review.ChampionReview(_CC_CHAMPION, _CC_RANKS)


class TestReviewedCrowdControl:
    """Illaoi's control is E's tether severance, which damages nothing.

    A control-armed holder shield (Fimbulwinter's Everlasting) reads the
    reviewed ``cc_kind`` off authored damage events; an unreviewed ability
    packet makes the whole timed fight fall back to coarse ordering, so the
    probe below is the reason these declarations exist.
    """

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        from src.calculator.champions import illaoi

        assert illaoi.MODULE_CC == {
            "W": "none",
            "R": "none",
            "P": "none",
            "Q": "none",
            "E": "slow",
        }
        assert illaoi.parse_abilities.cc_kinds == illaoi.MODULE_CC

    def test_control_free_slots_name_every_word_their_text_contains(self):
        for slot, expected in [["W", []], ["R", []]]:
            assert _CC.control_hits(slot) == list(expected), slot

    def test_every_reviewed_part_carries_its_kind(self):
        """Q and E price no damage part, so their declaration lands nowhere."""
        assert _CC.kinds() == {"W": ["none"], "R": ["none"], "passive": ["none"]}

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = _CC.coverage()

        assert coverage["complete"] is True
        assert coverage["certification"] == "event_order_certified"
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
