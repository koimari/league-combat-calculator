"""Reviewed crowd control for K'Sante (MODULE_CC, wave 4B).

Ntofo slows, Path Maker stuns outside All Out, All Out itself stuns.
"""

from tests import cc_review

# ---------------------------------------------------------------------------
# Reviewed crowd control (MODULE_CC, wave 4B)
# ---------------------------------------------------------------------------

_CC_CHAMPION = "K'Sante"
_CC_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_CC = cc_review.ChampionReview(_CC_CHAMPION, _CC_RANKS)


class TestReviewedCrowdControl:
    """Ntofo slows, Path Maker stuns outside All Out, All Out itself stuns.

    A control-armed holder shield (Fimbulwinter's Everlasting) reads the
    reviewed ``cc_kind`` off authored damage events; an unreviewed ability
    packet makes the whole timed fight fall back to coarse ordering, so the
    probe below is the reason these declarations exist.
    """

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        from src.calculator.champions import ksante
        from src.calculator.champions.engine import CC_PER_PART

        assert ksante.MODULE_CC == {
            "Q": "slow",
            "W": CC_PER_PART,
            "R": "stun",
            "P": "none",
            "E": "none",
        }
        assert ksante.parse_abilities.cc_kinds == ksante.MODULE_CC

    def test_each_declared_kind_is_the_word_its_slot_text_uses(self):
        for slot, word in [["Q", "slow"], ["W", "stun"], ["R", "stun"]]:
            assert word in _CC.slot_text(slot), slot

    def test_every_reviewed_part_carries_its_kind(self):
        """E prices no damage part, so its declaration lands nowhere."""
        assert _CC.kinds() == {
            "Q": ["slow"],
            "W": ["stun"],
            "R": ["stun"],
            "passive": ["none"],
        }

    def test_reviewed_kinds_follow_the_other_branch(self):
        """All Out: Path Maker does not apply its knock back and stun, so W is 'none'."""
        assert _CC.kinds(all_out=True) == {
            "Q": ["slow"],
            "W": ["none"],
            "R": ["stun"],
            "passive": ["none"],
        }

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = _CC.coverage()

        assert coverage["complete"] is True
        assert coverage["certification"] == "event_order_certified"
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
