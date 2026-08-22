"""Reviewed crowd control for Gangplank (MODULE_CC, wave 4B).

Powder Keg and every cannon wave slow; the burn and Parrrley do not.
"""

from tests import cc_review

# ---------------------------------------------------------------------------
# Reviewed crowd control (MODULE_CC, wave 4B)
# ---------------------------------------------------------------------------

_CC_CHAMPION = "Gangplank"
_CC_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_CC = cc_review.ChampionReview(_CC_CHAMPION, _CC_RANKS)


class TestReviewedCrowdControl:
    """Powder Keg and every cannon wave slow; the burn and Parrrley do not.

    A control-armed holder shield (Fimbulwinter's Everlasting) reads the
    reviewed ``cc_kind`` off authored damage events; an unreviewed ability
    packet makes the whole timed fight fall back to coarse ordering, so the
    probe below is the reason these declarations exist.
    """

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        from src.calculator.champions import gangplank

        assert gangplank.MODULE_CC == {
            "P": "none",
            "Q": "none",
            "E": "slow",
            "R": "slow",
        }
        assert gangplank.parse_abilities.cc_kinds == gangplank.MODULE_CC

    def test_each_declared_kind_is_the_word_its_slot_text_uses(self):
        for slot, word in [["E", "slow"], ["R", "slow"]]:
            assert word in _CC.slot_text(slot), slot

    def test_control_free_slots_name_every_word_their_text_contains(self):
        for slot, expected in [["P", []], ["Q", []]]:
            assert _CC.control_hits(slot) == list(expected), slot

    def test_every_reviewed_part_carries_its_kind(self):
        assert _CC.kinds() == {"Q": ["none"], "E": ["slow"], "R": ["slow"]}

    def test_reviewed_kinds_follow_the_other_branch(self):
        """The burn row carries the review once it prices any proc."""
        assert _CC.kinds(**{"p_procs": 2}) == {
            "passive": ["none"],
            "Q": ["none"],
            "E": ["slow"],
            "R": ["slow"],
        }

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = _CC.coverage()

        assert coverage["complete"] is True
        assert coverage["certification"] == "event_order_certified"
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


def test_the_packet_states_gangplanks_proc_count_and_ult_upgrades():
    """The passive prices ten proc legs; both R upgrades author a row."""
    from tests import row_review

    assert row_review.parts("Gangplank", "passive", p_procs=1)[0].count == 10
    upgraded = row_review.parts(
        "Gangplank", "R", r_fire_at_will=True, r_deaths_daughter=True
    )
    assert len(upgraded) == 2
