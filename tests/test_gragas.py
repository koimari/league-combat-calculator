"""Reviewed crowd control for Gragas (MODULE_CC, wave 4B).

Barrel Roll slows; Body Slam and Explosive Cask lead with a knock back.
"""

from tests import cc_review

# ---------------------------------------------------------------------------
# Reviewed crowd control (MODULE_CC, wave 4B)
# ---------------------------------------------------------------------------

_CC_CHAMPION = "Gragas"
_CC_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_CC = cc_review.ChampionReview(_CC_CHAMPION, _CC_RANKS)


class TestReviewedCrowdControl:
    """Barrel Roll slows; Body Slam and Explosive Cask lead with a knock back.

    A control-armed holder shield (Fimbulwinter's Everlasting) reads the
    reviewed ``cc_kind`` off authored damage events; an unreviewed ability
    packet makes the whole timed fight fall back to coarse ordering, so the
    probe below is the reason these declarations exist.
    """

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        from src.calculator.champions import gragas

        assert gragas.MODULE_CC == {
            "Q": "slow",
            "W": "none",
            "E": "knockback",
            "R": "knockback",
            "P": "none",
        }
        assert gragas.parse_abilities.cc_kinds == gragas.MODULE_CC

    def test_each_declared_kind_is_the_word_its_slot_text_uses(self):
        for slot, word in [["Q", "slow"], ["E", "knock"], ["R", "knock"]]:
            assert word in _CC.slot_text(slot), slot

    def test_control_free_slots_name_every_word_their_text_contains(self):
        for slot, expected in [["W", []]]:
            assert _CC.control_hits(slot) == list(expected), slot

    def test_every_reviewed_part_carries_its_kind(self):
        assert _CC.kinds() == {
            "Q": ["slow"],
            "W": ["none"],
            "E": ["knockback"],
            "R": ["knockback"],
        }

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = _CC.coverage()

        assert coverage["complete"] is True
        assert coverage["certification"] == "event_order_certified"
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


def test_the_packet_states_gragass_empowered_auto_and_fermented_q():
    """W empowers the next auto; a fully fermented Q still prices."""
    from tests import row_review

    assert row_review.entry("Gragas", "W")["empowers_next_auto"]
    assert row_review.priced("Gragas", "Q", q_fully_fermented=True) > 0
