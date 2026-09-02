"""Reviewed crowd control for Mordekaiser (MODULE_CC), and E's claw delay.

Obliterate only damages; Death's Grasp deals its damage and pulls on the
same claw, 0.5 seconds after the cast, which the packet now authors.
"""

from src.calculator.champions import mordekaiser, parse_champion_abilities
from tests import cc_review

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


class TestReviewedCrowdControl:
    """Mordekaiser's reviewed crowd control, and the delay that carries E.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Mordekaiser")
        assert mordekaiser.MODULE_CC == {
            "Q": "none",
            "E": "pull",
            "P": "none",
            "W": "none",
            "R": "slow",
        }
        assert mordekaiser.parse_abilities.cc_kinds == mordekaiser.MODULE_CC
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert "pulls them over 250 units" in cc_review.slot_text(data, "E")

    def test_deaths_grasp_lands_on_its_sourced_claw_delay(self):
        data = cc_review.kit("Mordekaiser")
        assert "After 0.5 seconds, it deals magic damage to enemies within" in (
            data["abilities"]["E"][0]["effects"][1]["description"]
        )
        (part,) = parse_champion_abilities(data, 18, 100.0, _RANKS)["E"]["parts"]
        assert part.time_offset == 0.5
        assert part.cc_kind == "pull"

    def test_the_state_only_slots_have_no_part_to_carry_their_kind(self):
        """W and R deal no enemy damage, so the kinds declared for them
        land on nothing: R's 75% cast-time slow is the kit's fact and the
        Realm of Death row prices no part it could ride."""
        data = cc_review.kit("Mordekaiser")
        parsed = parse_champion_abilities(data, 18, 100.0, _RANKS)
        assert "slowing them by 75%" in cc_review.slot_text(data, "R")
        for slot in ("W", "R"):
            assert cc_review.declared_parts(parsed, slot) == (), slot

    def test_the_reviewed_kit_clears_the_control_armed_scan(self):
        assert cc_review.unreviewed_ability_slots("Mordekaiser") == []
        coverage = cc_review.fimbulwinter_coverage("Mordekaiser")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
