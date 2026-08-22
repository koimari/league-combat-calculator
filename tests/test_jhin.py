"""Reviewed crowd control for Jhin (MODULE_CC, wave 4B).

Deadly Flourish roots a marked champion; the trap and R's bullets slow.
"""

from tests import cc_review

# ---------------------------------------------------------------------------
# Reviewed crowd control (MODULE_CC, wave 4B)
# ---------------------------------------------------------------------------

_CC_CHAMPION = "Jhin"
_CC_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_CC = cc_review.ChampionReview(_CC_CHAMPION, _CC_RANKS)


class TestReviewedCrowdControl:
    """Deadly Flourish roots a marked champion; the trap and R's bullets slow.

    A control-armed holder shield (Fimbulwinter's Everlasting) reads the
    reviewed ``cc_kind`` off authored damage events; an unreviewed ability
    packet makes the whole timed fight fall back to coarse ordering, so the
    probe below is the reason these declarations exist.
    """

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        from src.calculator.champions import jhin

        assert jhin.MODULE_CC == {"Q": "none", "W": "root", "E": "slow", "R": "slow"}
        assert jhin.parse_abilities.cc_kinds == jhin.MODULE_CC

    def test_each_declared_kind_is_the_word_its_slot_text_uses(self):
        for slot, word in [["W", "root"], ["E", "slow"], ["R", "slow"]]:
            assert word in _CC.slot_text(slot), slot

    def test_control_free_slots_name_every_word_their_text_contains(self):
        for slot, expected in [["Q", []]]:
            assert _CC.control_hits(slot) == list(expected), slot

    def test_every_reviewed_part_carries_its_kind(self):
        assert _CC.kinds() == {
            "Q": ["none"],
            "W": ["root"],
            "E": ["slow"],
            "R": ["slow"],
        }

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = _CC.coverage()

        assert coverage["complete"] is True
        assert coverage["certification"] == "event_order_certified"
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
