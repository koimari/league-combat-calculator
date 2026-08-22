"""Reviewed crowd control for Graves (MODULE_CC, wave 4B).

Only Smoke Screen controls, and it slows.
"""

from tests import cc_review

# ---------------------------------------------------------------------------
# Reviewed crowd control (MODULE_CC, wave 4B)
# ---------------------------------------------------------------------------

_CC_CHAMPION = "Graves"
_CC_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_CC = cc_review.ChampionReview(_CC_CHAMPION, _CC_RANKS)


class TestReviewedCrowdControl:
    """Only Smoke Screen controls, and it slows.

    A control-armed holder shield (Fimbulwinter's Everlasting) reads the
    reviewed ``cc_kind`` off authored damage events; an unreviewed ability
    packet makes the whole timed fight fall back to coarse ordering, so the
    probe below is the reason these declarations exist.
    """

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        from src.calculator.champions import graves

        assert graves.MODULE_CC == {"Q": "none", "W": "slow", "R": "none"}
        assert graves.parse_abilities.cc_kinds == graves.MODULE_CC

    def test_each_declared_kind_is_the_word_its_slot_text_uses(self):
        for slot, word in [["W", "slow"]]:
            assert word in _CC.slot_text(slot), slot

    def test_control_free_slots_name_every_word_their_text_contains(self):
        for slot, expected in [["Q", []], ["R", []]]:
            assert _CC.control_hits(slot) == list(expected), slot

    def test_every_reviewed_part_carries_its_kind(self):
        assert _CC.kinds() == {"Q": ["none"], "W": ["slow"], "R": ["none"]}

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = _CC.coverage()

        assert coverage["complete"] is True
        assert coverage["certification"] == "event_order_certified"
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


def test_the_packet_states_the_shotgun_override_and_a_two_leg_q():
    """The passive replaces the auto with all pellets; Q is smoke plus powder."""
    from tests import row_review

    override = row_review.entry("Graves", "passive", p_critical_pellets=True)[
        "auto_attack_override"
    ]
    assert override["damage_ratio"] > 2.0
    assert len(row_review.parts("Graves", "Q")) == 2
