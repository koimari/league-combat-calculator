"""Tests for the Rengar champion module."""

from src.calculator.champions import parse_champion_abilities, rengar
from src.calculator.champions.slot_cc import CC_PER_PART
from src.calculator.data_fetcher import get_champion
from tests import cc_review


def _e_part(ferocity):
    """The E part set the fight prices at this Ferocity.

    Bola Strike carries BOTH answers on one entry — ``parts`` is the base
    bola that slows, ``ferocity_parts`` the empowered one that roots — and
    ``damage.py`` prices the second set once the cast consumes the 4-stack
    cap.  Reading whichever set that cast spends is what makes the control
    answer per-branch rather than per-slot.
    """
    abilities = parse_champion_abilities(
        get_champion("Rengar"),
        18,
        0.0,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_options={"p_ferocity": ferocity},
    )
    key = "ferocity_parts" if ferocity >= 4 else "parts"
    (part,) = abilities["E"][key]
    return part


class TestReviewedCrowdControl:
    """Rengar's reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Rengar")
        assert rengar.MODULE_CC == {
            "Q": "none",
            "W": "none",
            "E": CC_PER_PART,
            "P": "none",
            "R": "none",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        # R's damage row is the empowered attack's armour-reduction rider
        # and P is the Ferocity state row, so neither carries an event.
        assert rengar.MODULE_CC["R"] == "none"
        assert rengar.MODULE_CC["P"] == "none"

    def test_e_answers_per_ferocity_branch_because_the_bonus_changes_it(self):
        e_text = cc_review.slot_text(cc_review.kit("Rengar"), "E")
        assert "slows them for 1.75 seconds" in e_text
        assert "the target is rooted instead of slowed" in e_text
        assert rengar.MODULE_CC["E"] == CC_PER_PART
        assert _e_part(0).cc_kind == "slow"
        assert _e_part(4).cc_kind == "root"
