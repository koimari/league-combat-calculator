"""Tests for the Qiyana champion module."""

from src.calculator.champions import parse_champion_abilities, qiyana
from src.calculator.data_fetcher import get_champion
from tests import cc_review
from src.calculator.champions.engine import CC_PER_PART


def _q_part(variant):
    abilities = parse_champion_abilities(
        get_champion("Qiyana"),
        18,
        0.0,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_options={"q_variant": variant},
    )
    (part,) = abilities["Q"]["parts"]
    return part


class TestReviewedCrowdControl:
    """Qiyana's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Qiyana")
        assert qiyana.MODULE_CC == {"Q": CC_PER_PART, "E": "none", "R": "stun"}
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        # R's windblast knocks back but damages nobody; the priced row is
        # the shockwave, which damages and stuns.
        r_text = cc_review.slot_text(data, "R")
        assert "knocks back enemies hit by 375 units" in r_text
        assert "dealing physical damage to enemies hit, stunning them" in r_text
        # P and W are absent: both are on-hit riders on the auto stream.
        assert "P" not in qiyana.MODULE_CC
        assert "W" not in qiyana.MODULE_CC

    def test_q_answers_per_element_and_leaves_the_grouped_index_unreviewed(self):
        q_text = cc_review.slot_text(cc_review.kit("Qiyana"), "Q")
        assert "river: the blast roots enemies hit for 0.5 seconds" in q_text
        assert qiyana.MODULE_CC["Q"] == CC_PER_PART
        # Index 1 is the option's grouped "brush/river" element, and the
        # two disagree, so it carries no kind rather than one only half of
        # it applies.
        assert _q_part(0).cc_kind == "none"
        assert _q_part(1).cc_kind is None
        assert _q_part(2).cc_kind == "none"

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Qiyana") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Qiyana")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
