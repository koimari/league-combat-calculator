"""Reviewed crowd control for Hwei (MODULE_CC, wave 4B).

Every mood subject carries its own kind; only P is a whole-slot answer.
"""

from tests import cc_review

# ---------------------------------------------------------------------------
# Reviewed crowd control (MODULE_CC, wave 4B)
# ---------------------------------------------------------------------------

_CC_CHAMPION = "Hwei"
_CC_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_CC = cc_review.ChampionReview(_CC_CHAMPION, _CC_RANKS)


class TestReviewedCrowdControl:
    """Every mood subject carries its own kind; only P is a whole-slot answer.

    A control-armed holder shield (Fimbulwinter's Everlasting) reads the
    reviewed ``cc_kind`` off authored damage events; an unreviewed ability
    packet makes the whole timed fight fall back to coarse ordering, so the
    probe below is the reason these declarations exist.
    """

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        from src.calculator.champions import hwei
        from src.calculator.champions.engine import CC_PER_PART

        assert hwei.MODULE_CC == {
            "P": "none",
            "Q": CC_PER_PART,
            "E": CC_PER_PART,
            "R": CC_PER_PART,
        }
        assert hwei.parse_abilities.cc_kinds == hwei.MODULE_CC

    def test_each_declared_kind_is_the_word_its_slot_text_uses(self):
        for slot, word in [["E", "fear"], ["R", "slow"]]:
            assert word in _CC.slot_text(slot), slot

    def test_control_free_slots_name_every_word_their_text_contains(self):
        for slot, expected in [["P", []]]:
            assert _CC.control_hits(slot) == list(expected), slot

    def test_every_reviewed_part_carries_its_kind(self):
        assert _CC.kinds() == {
            "passive": ["none"],
            "Q": ["none"],
            "E": ["fear"],
            "R": ["none", "slow"],
        }

    def test_reviewed_kinds_follow_the_second_branch(self):
        """Molten Fissure's fissure slows, Gaze of the Abyss roots."""
        assert _CC.kinds(q_variant=2, e_variant=1) == {
            "passive": ["none"],
            "Q": ["none", "slow"],
            "E": ["root"],
            "R": ["none", "slow"],
        }

    def test_reviewed_kinds_follow_the_third_branch(self):
        """Crushing Maw slows everything it damages."""
        assert _CC.kinds(e_variant=2) == {
            "passive": ["none"],
            "Q": ["none"],
            "E": ["slow"],
            "R": ["none", "slow"],
        }

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = _CC.coverage()

        assert coverage["complete"] is True
        assert coverage["certification"] == "event_order_certified"
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


def test_the_signature_passive_is_not_silently_dropped():
    """Hwei's Signature of the Visionary prices its armed triggers."""
    from tests import row_review

    passive = row_review.entry("Hwei", "passive", p_triggers=2)
    assert passive["proc_count"] == 2
    assert passive["damage_events"]
