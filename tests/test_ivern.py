"""Reviewed crowd control for Ivern (MODULE_CC, wave 4B).

Rootcaller roots, Triggerseed slows, and only Daisy's smash knocks up.
"""

from tests import cc_review

# ---------------------------------------------------------------------------
# Reviewed crowd control (MODULE_CC, wave 4B)
# ---------------------------------------------------------------------------

_CC_CHAMPION = "Ivern"
_CC_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_CC = cc_review.ChampionReview(_CC_CHAMPION, _CC_RANKS)


class TestReviewedCrowdControl:
    """Rootcaller roots, Triggerseed slows, and only Daisy's smash knocks up.

    A control-armed holder shield (Fimbulwinter's Everlasting) reads the
    reviewed ``cc_kind`` off authored damage events; an unreviewed ability
    packet makes the whole timed fight fall back to coarse ordering, so the
    probe below is the reason these declarations exist.
    """

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        from src.calculator.champions import ivern
        from src.calculator.champions.engine import CC_PER_PART

        assert ivern.MODULE_CC == {
            "Q": "root",
            "E": "slow",
            "R": CC_PER_PART,
            "P": "none",
            "W": "none",
        }
        assert ivern.parse_abilities.cc_kinds == ivern.MODULE_CC

    def test_each_declared_kind_is_the_word_its_slot_text_uses(self):
        for slot, word in [["Q", "root"], ["E", "slow"]]:
            assert word in _CC.slot_text(slot), slot

    def test_every_reviewed_part_carries_its_kind(self):
        assert _CC.kinds() == {"Q": ["root"], "E": ["slow"], "R": ["knockup", "none"]}

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = _CC.coverage()

        assert coverage["complete"] is True
        assert coverage["certification"] == "event_order_certified"
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
