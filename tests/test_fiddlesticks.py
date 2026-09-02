"""Reviewed crowd control for Fiddlesticks (MODULE_CC, wave 4B).

Terrify fears, Reap slows; the doubled branch fears nothing, which is why Q's kind rides its part.
"""

from tests import cc_review

# ---------------------------------------------------------------------------
# Reviewed crowd control (MODULE_CC, wave 4B)
# ---------------------------------------------------------------------------

_CC_CHAMPION = "Fiddlesticks"
_CC_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_CC = cc_review.ChampionReview(_CC_CHAMPION, _CC_RANKS)


class TestReviewedCrowdControl:
    """Terrify fears, Reap slows; the doubled branch fears nothing, so Q's kind rides its part.

    A control-armed holder shield (Fimbulwinter's Everlasting) reads the
    reviewed ``cc_kind`` off authored damage events; an unreviewed ability
    packet makes the whole timed fight fall back to coarse ordering, so the
    probe below is the reason these declarations exist.
    """

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        from src.calculator.champions import fiddlesticks
        from src.calculator.champions.engine import CC_PER_PART

        assert fiddlesticks.MODULE_CC == {
            "Q": CC_PER_PART,
            "W": "none",
            "E": "slow",
            "R": "none",
        }
        assert fiddlesticks.parse_abilities.cc_kinds == fiddlesticks.MODULE_CC

    def test_each_declared_kind_is_the_word_its_slot_text_uses(self):
        for slot, word in [["Q", "fear"], ["E", "slow"]]:
            assert word in _CC.slot_text(slot), slot

    def test_control_free_slots_name_every_word_their_text_contains(self):
        for slot, expected in [["W", []], ["R", []]]:
            assert _CC.control_hits(slot) == list(expected), slot

    def test_every_reviewed_part_carries_its_kind(self):
        assert _CC.kinds() == {
            "Q": ["fear"],
            "W": ["none"],
            "E": ["slow"],
            "R": ["none"],
        }

    def test_reviewed_kinds_follow_the_other_branch(self):
        """A target that 'cannot be affected by it again' is not feared."""
        assert _CC.kinds(q_target_already_feared=True) == {
            "Q": ["none"],
            "W": ["none"],
            "E": ["slow"],
            "R": ["none"],
        }

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = _CC.coverage()

        assert coverage["complete"] is True
        assert coverage["certification"] == "event_order_certified"
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


def test_the_packet_prices_every_drain_and_crowstorm_tick():
    """Both channels are one row carrying the tick count the option asks for."""
    from tests import row_review

    assert row_review.parts("Fiddlesticks", "W", w_ticks=8)[0].count == 8
    assert row_review.parts("Fiddlesticks", "R", r_ticks=20)[0].count == 20
