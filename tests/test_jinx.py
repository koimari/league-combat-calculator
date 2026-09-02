"""Reviewed crowd control for Jinx (MODULE_CC, wave 4B).

Zap! slows, a Chomper roots, the rocket only explodes.
"""

from tests import cc_review

# ---------------------------------------------------------------------------
# Reviewed crowd control (MODULE_CC, wave 4B)
# ---------------------------------------------------------------------------

_CC_CHAMPION = "Jinx"
_CC_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_CC = cc_review.ChampionReview(_CC_CHAMPION, _CC_RANKS)


class TestReviewedCrowdControl:
    """The rocket only explodes; W slows and E's Chomper roots.

    A control-armed holder shield (Fimbulwinter's Everlasting) reads the
    reviewed ``cc_kind`` off authored damage events; an unreviewed ability
    packet makes the whole timed fight fall back to coarse ordering, so the
    probe below is the reason these declarations exist.
    """

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        from src.calculator.champions import jinx

        assert jinx.MODULE_CC == {
            "W": "slow",
            "E": "root",
            "R": "none",
            "P": "none",
            "Q": "none",
        }
        assert jinx.parse_abilities.cc_kinds == jinx.MODULE_CC

    def test_the_declared_kinds_are_the_ones_the_text_gives(self):
        assert "reveals and slows them for 2 seconds" in _CC.slot_text("W")
        assert "knocking them down and rooting them for 1.5 seconds" in _CC.slot_text(
            "E"
        )

    def test_control_free_slots_name_every_word_their_text_contains(self):
        for slot, expected in [["R", []]]:
            assert _CC.control_hits(slot) == list(expected), slot

    def test_every_reviewed_part_carries_its_kind(self):
        """P is a takedown-stack buff row with no part to carry its "none"."""
        assert _CC.kinds() == {
            "Q": ["none"],
            "W": ["slow"],
            "E": ["root"],
            "R": ["none"],
        }

    def test_flame_chompers_land_on_their_sourced_arming_time(self):
        """The Chomper cannot explode before it arms, 0.5 s after the cast."""
        from src.calculator.champions import jinx, parse_champion_abilities
        from src.calculator.data_fetcher import get_champion

        assert "arming after 0.5 seconds" in _CC.slot_text("E")
        parsed = parse_champion_abilities(
            get_champion(_CC_CHAMPION), 18, 100.0, {"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        (part,) = parsed["E"]["parts"]
        assert part.time_offset == jinx._E_ARMING_SECONDS == 0.5

    def test_a_timed_fimbulwinter_fight_is_now_complete(self):
        """Every ability event the kit emits carries a reviewed kind."""
        coverage = _CC.coverage()

        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
