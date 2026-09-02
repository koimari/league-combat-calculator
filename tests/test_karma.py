"""Reviewed crowd control for Karma (MODULE_CC, wave 4B).

Inner Flame slows; Focused Resolve roots only on its second hit.
"""

from tests import cc_review

# ---------------------------------------------------------------------------
# Reviewed crowd control (MODULE_CC, wave 4B)
# ---------------------------------------------------------------------------

_CC_CHAMPION = "Karma"
_CC_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_CC = cc_review.ChampionReview(_CC_CHAMPION, _CC_RANKS)


class TestReviewedCrowdControl:
    """Inner Flame slows; Focused Resolve roots only on its second hit.

    A control-armed holder shield (Fimbulwinter's Everlasting) reads the
    reviewed ``cc_kind`` off authored damage events; an unreviewed ability
    packet makes the whole timed fight fall back to coarse ordering, so the
    probe below is the reason these declarations exist.
    """

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        from src.calculator.champions import karma
        from src.calculator.champions.engine import CC_PER_PART

        assert karma.MODULE_CC == {
            "Q": "slow",
            "W": CC_PER_PART,
            "P": "none",
            "E": "none",
            "R": "none",
        }
        assert karma.parse_abilities.cc_kinds == karma.MODULE_CC

    def test_each_declared_kind_is_the_word_its_slot_text_uses(self):
        for slot, word in [["Q", "slow"], ["W", "root"]]:
            assert word in _CC.slot_text(slot), slot

    def test_every_reviewed_part_carries_its_kind(self):
        assert _CC.kinds() == {"Q": ["slow"], "W": ["none", "root"]}

    def test_reviewed_kinds_follow_the_other_branch(self):
        """A broken tether never reaches the root."""
        assert _CC.kinds(w_tether_holds=False) == {"Q": ["slow"], "W": ["none"]}

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = _CC.coverage()

        assert coverage["complete"] is True
        assert coverage["certification"] == "event_order_certified"
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
