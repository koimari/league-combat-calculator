"""Reviewed crowd control for Garen (MODULE_CC, wave 4B).

Garen's damaging casts apply no immobilize and no slow.
"""

from tests import cc_review

# ---------------------------------------------------------------------------
# Reviewed crowd control (MODULE_CC, wave 4B)
# ---------------------------------------------------------------------------

_CC_CHAMPION = "Garen"
_CC_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_CC = cc_review.ChampionReview(_CC_CHAMPION, _CC_RANKS)


class TestReviewedCrowdControl:
    """Garen's damaging casts apply no immobilize and no slow.

    A control-armed holder shield (Fimbulwinter's Everlasting) reads the
    reviewed ``cc_kind`` off authored damage events; an unreviewed ability
    packet makes the whole timed fight fall back to coarse ordering, so the
    probe below is the reason these declarations exist.
    """

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        from src.calculator.champions import garen

        assert garen.MODULE_CC == {
            "Q": "none",
            "E": "none",
            "R": "none",
            "P": "none",
            "W": "none",
        }
        assert garen.parse_abilities.cc_kinds == garen.MODULE_CC

    def test_control_free_slots_name_every_word_their_text_contains(self):
        for slot, expected in [["Q", ["slow"]], ["E", []], ["R", []]]:
            assert _CC.control_hits(slot) == list(expected), slot

    def test_every_reviewed_part_carries_its_kind(self):
        assert _CC.kinds() == {"Q": ["none"], "E": ["none"], "R": ["none"]}

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = _CC.coverage()

        assert coverage["complete"] is True
        assert coverage["certification"] == "event_order_certified"
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


def test_the_packet_states_judgments_spin_count_and_shred_threshold():
    """E's spins are one counted row and its shred names the hits it needs."""
    from tests import row_review

    entry = row_review.entry("Garen", "E")
    assert entry["parts"][0].count >= 7
    assert entry["target_debuff"]["threshold_hits"] == 6
